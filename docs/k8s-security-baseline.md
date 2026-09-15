# K8s 보안 기준선

대상: `s3-monitor` Deployment (kind/EKS 공통)

Kubernetes로 확장하는 초기 시점에는 보안 설정을 의도적으로 적용하지 않고
현재 상태를 먼저 점검했다. 이 문서는 그 점검 결과와, 이후 각 항목을
어떻게 해소했는지를 정리한다.

각 항목은 추정이 아니라 **명령으로 확인한 결과**다. 재현 명령을 함께 남긴다.

```bash
POD=$(kubectl get pod -l app=s3-monitor -o jsonpath='{.items[0].metadata.name}')
```

---

## 요약

| # | 문제 | 위험 | 상태 |
|---|---|---|---|
| 1 | 컨테이너가 root(uid 0)로 실행 | 패키지 설치, 임의 파일 쓰기, 커널 기능 요청 | **해결** |
| 2 | Pod 간 통신에 제한 없음 | 한 Pod 탈취 시 클러스터 내 횡적 이동 | **해결** |
| 3 | 사용하지 않는 SA 토큰이 자동 마운트 | 최소 권한 원칙 위배. SA 권한 확대 시 즉시 침해 경로 | **해결** |
| 4 | 루트 파일 시스템 쓰기 가능 | 악성 스크립트 주입, 바이너리 교체 | **해결** |
| 5 | 불필요한 Linux capability 보유 | 네트워크 조작(NET_RAW), 파일 권한 우회(DAC_OVERRIDE) | **해결** |
| 6 | 자원 상한이 느슨함 (QoS: Burstable) | 자원 폭주 시 같은 노드의 다른 Pod가 eviction (자원 고갈형 DoS) | requests 설정됨, QoS는 Burstable 유지 |
| 7 | Egress 정책 부재 | 컨테이너 탈취 시 데이터 유출이나 외부 통신을 막지 못함 | 미해결 — 근거는 [decisions.md](./decisions.md) 참고 |
| 8 | 정적 AWS 액세스 키가 평문 Secret에 존재 | 키 유출 시 AWS 계정 전체 위험, 로테이션 부재 | **해결** (IRSA 전환) |

---

## 1. 컨테이너가 root로 실행

```bash
kubectl exec $POD -- id
# uid=0(root) gid=0(root) groups=0(root)
```

**문제** — `securityContext`가 없어 컨테이너 기본값인 root로 실행된다.

**위험** — 앱은 8000 포트에서 HTTP 응답만 하면 되는데, 패키지 설치·임의 경로 쓰기·커널 기능 요청 권한이 모두 붙어 있다. 필요 없는 권한이 기본으로 딸려온 형태다.

**해결** — Dockerfile에 숫자 UID(`USER 1000`)로 non-root 유저를 지정하고 `securityContext.runAsNonRoot: true`를 적용했다. 문자열 사용자명(`USER appuser`)으로는 kubelet이 실제 UID를 사전에 검증할 수 없어 컨테이너 시작 자체가 거부되는 것을 확인한 뒤 숫자로 전환했다.

```bash
kubectl exec $POD -- id
# uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)
```

---

## 2. Pod 간 통신에 제한 없음

```bash
kubectl run tmp --rm -it --image=busybox:1.36 --restart=Never -- \
  wget -qO- --timeout=2 http://$(kubectl get pod $POD -o jsonpath='{.status.podIP}'):8000/livez
```

**문제** — K8s의 기본값은 all-allow다. 클러스터 안의 어떤 Pod든 다른 Pod의 어떤 포트에든 접근할 수 있다. 아무 관계 없는 임시 Pod에서 앱에 직접 닿는 것을 확인했다.

**위험** — 공격자가 클러스터 내 아무 Pod나 하나 탈취하면 나머지 전부에 무제한 접근할 수 있다. 침해가 한 지점에 머물지 않고 퍼진다(횡적 이동).

**해결** — `default-deny-ingress`로 모든 인바운드를 기본 차단한 뒤, `allow-from-ingress-nginx`로 ingress-nginx 네임스페이스에서 오는 트래픽만 허용했다(kind 기본 CNI는 NetworkPolicy를 무시하므로 Calico로 전환 필요). 임의 Pod에서의 직접 접근은 차단되고, Ingress 경유 접근은 정상 동작하는 것을 확인했다. Egress(나가는 트래픽) 방향은 별도 항목(7번)으로 다룬다.

---

## 3. 사용하지 않는 ServiceAccount 토큰이 자동 마운트

```bash
kubectl get pod $POD -o jsonpath='{.spec.serviceAccountName}'          # default
kubectl exec $POD -- cat /var/run/secrets/kubernetes.io/serviceaccount/token | head -c 50
kubectl auth can-i --list --as=system:serviceaccount:default:default
kubectl auth can-i get secrets --as=system:serviceaccount:default:default   # no
```

**문제** — ServiceAccount를 지정한 적이 없는데 `default` SA가 붙었고, 그 토큰이 컨테이너 안에 파일로 마운트되어 있다. **이 앱은 K8s API를 전혀 호출하지 않는다.**

**확인된 사실** — 현재 `default` SA의 권한은 낮다. Secret 읽기 권한도 없다(`can-i get secrets` → `no`).

> **Secret을 읽는 주체와 Secret 값을 쓰는 주체가 다르다.**
> 앱이 API 서버에 요청해서 값을 얻는 것이 아니라, kubelet이 Pod를 만들 때
> 환경변수로 주입한다. 그래서 SA에 Secret 읽기 권한이 없어도 앱은 값을 갖고 있다.

**위험** — 지금은 권한이 낮아 무해하다. 그러나 **쓰지도 않는 자격증명이 모든 Pod에 자동으로 붙는 구조 자체가 문제다.** 누군가 나중에 이 SA에 권한을 부여하면 그 순간 모든 Pod가 침해 경로가 된다.

**해결** — 전용 ServiceAccount(`s3-monitor-sa`)를 만들고 `automountServiceAccountToken: false`를 적용했다. 적용 전후로 토큰 마운트 경로(`/var/run/secrets/kubernetes.io/serviceaccount/`) 자체가 사라지는 것을 확인했다(파일이 비는 게 아니라 마운트 지점 자체가 생성되지 않음). 가상 시나리오로 최소 권한 Role/RoleBinding을 설계해 `kubectl auth can-i`로 권한 경계까지 검증한 뒤, 실제 사용처가 없어 클러스터에서는 제거했다(코드는 `k8s/experiments/`에 학습용으로 보존).

---

## 4. 루트 파일 시스템 쓰기 가능

```bash
kubectl exec $POD -- touch /root/test.txt; echo $?    # 0
```

**문제** — `readOnlyRootFilesystem`이 설정되지 않아 컨테이너가 어느 경로에든 쓸 수 있다.

**위험** — 컨테이너를 탈취한 공격자가 악성 스크립트를 심거나 기존 바이너리를 교체할 수 있다. 앱은 실행 중 파일을 쓸 일이 없으므로 이 권한은 불필요하다.

**해결** — 코드가 로컬 디스크에 쓰기 작업을 하지 않음을 먼저 확인(boto3로 AWS API만 호출)한 뒤 `readOnlyRootFilesystem: true`를 적용했다. 적용 후 `touch` 시도가 `Read-only file system`으로 거부되는 것을 확인했다. 별도 `emptyDir` 마운트는 필요하지 않았다.

---

## 5. 불필요한 Linux capability 보유

```bash
kubectl exec $POD -- cat /proc/1/status | grep -i cap
# CapEff: 00000000a80425fb
capsh --decode=a80425fb
```

**문제** — `a80425fb`는 컨테이너 런타임의 기본 capability 14개다. 런타임이 root의 전체 권한에서 상당수를 이미 떼어냈으나, 남은 것도 앱에는 필요 없다.

| capability | 무엇을 할 수 있나 |
|---|---|
| `CAP_NET_RAW` | raw 소켓 생성 → ARP 스푸핑, 패킷 스니핑 |
| `CAP_CHOWN`, `CAP_FOWNER`, `CAP_DAC_OVERRIDE` | 파일 소유권·권한 무시 |
| `CAP_SETUID`, `CAP_SETGID` | 다른 사용자로 전환 |

**위험** — `CAP_NET_RAW`는 2번(무제한 Pod 간 통신)과 결합할 때 위력이 커진다. 파일 권한 계열은 4번과 이어진다. **개별로는 작아 보이는 항목들이 조합되면 공격 경로가 된다.**

**해결** — `capabilities.drop: ["ALL"]`과 `allowPrivilegeEscalation: false`를 적용했다. 이 앱은 네트워크 바인딩(8000번 포트, 비특권 포트)이나 파일시스템 조작 등 어떤 capability도 구조적으로 필요 없어, 적용 후에도 별도 실패 없이 정상 동작했다.

---

## 6. 자원 상한이 느슨함

```bash
kubectl get pod $POD -o jsonpath='{.status.qosClass}'    # Burstable
```

**문제** — `requests`와 `limits`가 일치하지 않아 QoS Class가 `Burstable`이다.

**위험** — 메모리가 실제로 고갈되면 kubelet이 Pod를 쫓아낸다(eviction). 순서는 QoS Class로 정해진다.

| QoS Class | 조건 | eviction 순서 |
|---|---|---|
| `BestEffort` | requests/limits 없음 | 가장 먼저 |
| `Burstable` | requests만 있거나 requests < limits | 중간 |
| `Guaranteed` | requests == limits | 마지막 |

**자원 제한을 안 건 Pod가 자기만 죽는 것이 아니라, 제한을 잘 건 옆 Pod까지 위협한다.**
한 컨테이너를 탈취한 공격자가 메모리를 폭주시켜 노드 전체를 마비시킬 수 있다(자원 고갈형 DoS).

**현재 상태** — `requests`(cpu 100m, memory 128Mi)와 `limits`(memory 256Mi)를 설정해 최소한의 상한은 있으나, 둘이 일치하지 않아 QoS Class는 `Burstable`로 유지된다. `Guaranteed`로의 전환(requests==limits)은 보류했다 — 상한을 꽉 조이면 정상 트래픽 급증에도 OOMKill될 수 있어, 트래픽 패턴을 더 확인한 뒤 판단하는 것이 맞다고 봤다. 대신 `capabilities.drop` 등 securityContext 적용으로, 자원 폭주로 이어질 수 있는 다른 경로(권한 남용)는 별도로 차단했다.

---

## 7. Egress 정책 부재

```bash
kubectl exec $POD -- wget -qO- --timeout=2 https://example.com
# (현재는 제한 없이 외부로 나감)
```

**문제** — Egress(나가는 트래픽) 방향으로는 어떤 제한도 없다. 컨테이너가 임의의 외부 주소와 자유롭게 통신할 수 있다.

**위험** — 컨테이너가 탈취되면 데이터 유출(exfiltration)이나 C2(command and control) 통신을 막을 방법이 없다.

**진행 상황** — 설계까지 진행했으나 구현은 보류했다. DNS 예외(CoreDNS 대상)는 Ingress 정책(2번)과 대칭적으로 어렵지 않으나, AWS API(S3/IAM/STS/CloudTrail) 예외는 표준 K8s NetworkPolicy가 도메인 이름이 아닌 IP CIDR로만 제한 가능하다는 근본적 한계에 부딪혔다. 정석 해법(VPC Endpoint로 AWS API 트래픽을 애초에 인터넷 밖으로 내보내지 않는 것)까지 조사했고 구현 규모(Terraform 리소스 4~5개)도 크지 않다는 것을 확인했으나, 이미 대부분의 항목을 구현·검증한 시점에서 한계효용을 고려해 이번 라운드에서는 보류했다. 판단 근거는 [decisions.md](./decisions.md)에 정리했다.

---

## 8. 정적 AWS 액세스 키가 평문 Secret에 존재

```bash
kubectl get secret s3-monitor-secret -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d
# → 액세스 키가 그대로 출력된다. base64는 암호화가 아니다.
```

**문제** — 애플리케이션이 AWS API(S3, IAM, CloudTrail)를 호출하기 위해 정적 액세스 키를 Kubernetes Secret에 평문으로 담아 환경변수로 주입하고 있었다.

**위험** — 키가 유출되면 AWS 계정 권한 범위 내에서 임의의 행위가 가능하다. 정적 키는 자동 로테이션이 없어, 유출되어도 오래 방치되기 쉽다.

**해결** — IRSA(OIDC 기반 신뢰 체인: EKS OIDC issuer → IAM OIDC provider → IAM Role Trust Policy → STS)로 전환했다. 전용 ServiceAccount에 IAM Role을 연결(`eks.amazonaws.com/role-arn` annotation)하고, Permission Policy는 코드에서 실제로 호출하는 API만 추출해 구성했다(와일드카드 없이 10개 액션). Secret을 완전히 제거한 뒤 `AWS_ROLE_ARN`/`AWS_WEB_IDENTITY_TOKEN_FILE`만으로 모든 엔드포인트가 정상 동작하는 것을 확인했다.

```bash
kubectl exec $POD -- env | grep AWS
# AWS_ROLE_ARN=arn:aws:iam::<account>:role/s3-monitor-irsa-role
# AWS_WEB_IDENTITY_TOKEN_FILE=/var/run/secrets/eks.amazonaws.com/serviceaccount/token
# (AWS_ACCESS_KEY_ID 없음)
```