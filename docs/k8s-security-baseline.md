# K8s 보안 기준선 — Week 1 시점

기준일: 2026-08-20 (Week 1 종료)
대상: kind 클러스터의 `s3-monitor` Deployment

Week 1은 앱을 K8s에서 동작시키는 데 집중했고, 보안 설정은 의도적으로 적용하지 않았다.
이 문서는 그 시점의 상태를 기록한 것이며, Week 2에서 각 항목을 해소하며 "상태" 열을 갱신한다.

각 항목은 추정이 아니라 **명령으로 확인한 결과**다. 재현 명령을 함께 남긴다.

```bash
POD=$(kubectl get pod -l app=s3-monitor -o jsonpath='{.items[0].metadata.name}')
```

---

## 요약

| # | 문제 | 위험 | 상태 |
|---|---|---|---|
| 1 | 컨테이너가 root(uid 0)로 실행 | 패키지 설치, 임의 파일 쓰기, 커널 기능 요청 | 미해결 |
| 2 | Pod 간 통신에 제한 없음 | 한 Pod 탈취 시 클러스터 내 횡적 이동 | 미해결 |
| 3 | 사용하지 않는 SA 토큰이 자동 마운트 | 최소 권한 원칙 위배. SA 권한 확대 시 즉시 침해 경로 | 미해결 |
| 4 | 루트 파일 시스템 쓰기 가능 | 악성 스크립트 주입, 바이너리 교체 | 미해결 |
| 5 | 불필요한 Linux capability 보유 | 네트워크 조작(NET_RAW), 파일 권한 우회(DAC_OVERRIDE) | 미해결 |
| 6 | 자원 상한이 느슨함 (QoS: Burstable) | 자원 폭주 시 같은 노드의 다른 Pod가 eviction (자원 고갈형 DoS) | 미해결 |

---

## 1. 컨테이너가 root로 실행

```bash
kubectl exec $POD -- id
# uid=0(root) gid=0(root) groups=0(root)
```

**문제** — `securityContext`가 없어 컨테이너 기본값인 root로 실행된다.

**위험** — 앱은 8000 포트에서 HTTP 응답만 하면 되는데, 패키지 설치·임의 경로 쓰기·커널 기능 요청 권한이 모두 붙어 있다. 필요 없는 권한이 기본으로 딸려온 형태다.

**해결 예정** — Dockerfile에 non-root `USER` 추가 + `runAsNonRoot: true`

---

## 2. Pod 간 통신에 제한 없음

```bash
kubectl run tmp --rm -it --image=busybox:1.36 --restart=Never -- \
  wget -qO- --timeout=2 http://$(kubectl get pod $POD -o jsonpath='{.status.podIP}'):8000/livez
```

**문제** — K8s의 기본값은 all-allow다. 클러스터 안의 어떤 Pod든 다른 Pod의 어떤 포트에든 접근할 수 있다. 아무 관계 없는 임시 Pod에서 앱에 직접 닿는 것을 확인했다.

**위험** — 공격자가 클러스터 내 아무 Pod나 하나 탈취하면 나머지 전부에 무제한 접근할 수 있다. 침해가 한 지점에 머물지 않고 퍼진다(횡적 이동).

**해결 예정** — NetworkPolicy default-deny 후 필요한 경로만 허용

> kind 기본 CNI는 NetworkPolicy를 무시하므로 Calico를 넣은 클러스터가 필요하다.

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

**해결 예정** — `automountServiceAccountToken: false` + 앱 전용 SA와 최소 권한 Role

---

## 4. 루트 파일 시스템 쓰기 가능

```bash
kubectl exec $POD -- touch /root/test.txt; echo $?    # 0
```

**문제** — `readOnlyRootFilesystem`이 설정되지 않아 컨테이너가 어느 경로에든 쓸 수 있다.

**위험** — 컨테이너를 탈취한 공격자가 악성 스크립트를 심거나 기존 바이너리를 교체할 수 있다. 앱은 실행 중 파일을 쓸 일이 없으므로 이 권한은 불필요하다.

**해결 예정** — `readOnlyRootFilesystem: true`. 쓰기가 필요한 경로가 나오면 `emptyDir`로 그 경로만 마운트

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

**해결 예정** — `capabilities.drop: ["ALL"]`, `allowPrivilegeEscalation: false`

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

**해결 예정** — `requests`와 `limits`를 조정. 다만 `Guaranteed`로 갈지는 별도 판단이 필요하다 — 상한을 꽉 조이면 정상 트래픽 급증에도 OOMKill될 수 있다.

---

## Week 2 대응 계획

| 항목 | 해결 수단 | 예정 |
|---|---|---|
| 3 | 전용 ServiceAccount + Role, `automountServiceAccountToken: false` | Day 8 |
| 1, 4, 5, 6 | `securityContext`, Dockerfile non-root USER | Day 9 |
| 2 | NetworkPolicy default-deny (Calico 필요) | Day 12 |

각 항목 해소 시 이 문서의 "상태" 열을 갱신하고, 확인 명령의 출력이 어떻게 바뀌었는지 기록한다.