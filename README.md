# AWS S3 인프라 자동 점검 시스템

## 프로젝트 개요

Terraform으로 프로비저닝한 S3 인프라의 설정 변경을 CloudTrail로 추적하고, IAM 사용자의 권한 설정을 점검하는 AWS 인프라 자동 점검 시스템이다.
반복적인 점검 작업을 코드로 자동화하고, 안전하게 조치할 수 있는 구조를 목표로 한다.

이후 이 애플리케이션을 EKS 환경으로 확장하며 RBAC 최소 권한, IRSA(정적 자격증명 제거), Helm 기반 배포, ArgoCD를 통한 GitOps까지 구현했다. 단순히 컨테이너로 감싸는 것을 넘어, "탐지·조치 애플리케이션이 클라우드 네이티브 환경에서 어떻게 안전하고 견고하게 운영되어야 하는가"까지 확장한 것이다.

> 이 프로젝트에서 느낀 "탐지 이후"의 필요성이
> [aws-3tier-infra](https://github.com/winterconquest/aws-3tier-infra)로 이어졌다.
> 그쪽은 인프라를 직접 설계·구축하고 장애 복구와 모니터링을 실측 검증한 프로젝트다.

각 리소스와 구성에 대한 결정 근거는 [decisions.md](./docs/decisions.md)를 참고.

### 준실시간 탐지 흐름

S3 설정 변경 → CloudTrail 기록 → EventBridge 캐치 → Lambda 호출 → Slack 알림

### 보안 운영 관점에서의 기능

- IAM 권한 점검 모듈은 결과적으로 접근제어 정책이 의도대로 적용되고 있는지 검증하는 기능이다.
- S3 퍼블릭 액세스 점검은 보안 설정 상태를 지속적으로 관리하며 오탐지, 미탐지 없이 위험 설정을 걸러내는 기능이다.
- EKS 환경에서는 애플리케이션 자체의 권한 모델(RBAC, IRSA)도 같은 원칙 — 최소 권한, 명시적 예외 — 으로 설계했다.


## 배경

시스템 운영 업무를 하면서 느낀 점은, 점검 작업이 사람에 의존하는 한 누락과 일관성 문제가 발생하기 쉽다는 점이었다.
정형화된 작업을 코드로 자동화하면 점검 누락을 줄이고, 무엇보다 일관성 있는 기준을 적용할 수 있겠다고 판단했다.

한편 자동화는 이점만큼 위험성도 있기에, 단순 탐지에서 멈추지 않고 안전한 조치까지 함께 설계하는 것을 목표로 했다.
점검 결과를 사람이 확인할 수 있는 형태로 노출하고, 조치는 명시적으로 분리해 의도하지 않은 변경을 막는 구조를 지향한다.

이 원칙은 K8s 확장에서도 그대로 이어졌다. 애플리케이션이 AWS 리소스를 점검·조치할 권한을 어떻게 안전하게 위임받을 것인가라는 질문이, 정적 액세스 키에서 시작해 RBAC와 IRSA로 이어지는 확장의 출발점이었다. 배포가 안정적으로 이루어지는가, 사람이 실수로 클러스터 상태를 흐트러뜨려도 정해진 상태로 돌아오는가라는 질문은 Pod 다운타임 개선과 ArgoCD 도입으로 이어졌다.


## 아키텍처

```
Terraform
├── S3 버킷 프로비저닝 (퍼블릭 액세스 차단, KMS 암호화, 버전 관리, 로깅)
├── 준실시간 알림 시스템 (EventBridge + Lambda + Slack)
└── EKS 클러스터 (terraform-eks/) — VPC, 노드그룹, OIDC provider, IRSA용 IAM Role

boto3 + FastAPI
├── /s3-status       → S3 퍼블릭 액세스 설정 점검
├── /trail-history   → CloudTrail 설정 변경 이벤트 추적
├── /iam-status      → IAM 사용자 권한 상태 점검
├── /remediate       → 단일 버킷 조치 (dry-run 기본, 태그 기반 예외 처리)
└── /auto-remediate  → 점검 결과 기반 위험 버킷 일괄 조치 (dry-run 기본)

Kubernetes 배포 (정식: Helm, 참고용: Kustomize)
├── helm/s3-monitor/  → values.yaml(공통) + values-{kind,eks}.yaml(환경별)
│   ├── ServiceAccount — 전용 SA, 토큰 자동 마운트 비활성화, 최소 권한 RBAC
│   ├── IRSA — OIDC 기반 IAM Role, 정적 액세스 키 없이 AWS API 인증
│   ├── PodDisruptionBudget, HorizontalPodAutoscaler
│   └── securityContext — non-root, 읽기전용 루트 파일시스템, capability 전체 제거
└── k8s/ (Kustomize, 병행 유지 — k8s/README.md 참고)

ArgoCD (GitOps)
└── argocd/s3-monitor-app.yaml → Git 저장소 상태를 클러스터에 자동 동기화(selfHeal)
```

![Swagger UI - 점검·조치 엔드포인트](./docs/images/swagger-overview.png)

> 조회는 GET, 상태를 변경하는 조치는 POST로 분리

## 점검 시나리오

1. Terraform으로 퍼블릭 액세스가 차단된(기본값) S3 버킷 생성
2. 해당 버킷 설정 권한자가 퍼블릭 액세스 허용으로 변경
3. /s3-status에서 퍼블릭 액세스가 허용된 상태를 감지
4. /trail-history에서 해당 설정 변경 이벤트를 추적하여 변경자, 대상 버킷, 변경 시각, 변경 내용을 확인
5. /iam-status에서 IAM 사용자, 소속 그룹, 정책 목록을 조회해 불필요하게 부여된 권한이 있는지 점검
6. /auto-remediate에서 위험으로 식별된 버킷을 일괄 조치 (dry-run 기본, 태그 예외 적용)
7. 위험 변경 발생 시 EventBridge → Lambda → Slack으로 운영자에게 준실시간 알림

### 실행 결과

![s3-status - 버킷별 퍼블릭 액세스 상태 점검](./docs/images/s3-status-response.png)

> 각 버킷의 퍼블릭 액세스 차단 여부를 실제로 점검한 응답

![trail-history - 설정 변경 이벤트 추적](./docs/images/trail-history.png)

> 변경 시각·변경자·대상 버킷·변경 내용을 CloudTrail에서 추적

![iam-status - 과도한 권한 사용자 탐지](./docs/images/iam-status.png)

> AdministratorAccess가 부여된 사용자를 탐지한 응답

## Remediation 모듈

단순 점검에서 멈추지 않고, 위험한 설정을 자동으로 조치하는 모듈이다.
자동화의 안전성을 우선해 다음 두 가지 원칙으로 설계했다.

- **dry-run 모드 기본값**: 함수 인자에 `dry_run=True`를 기본값으로 설정.
  실제 변경 작업은 `dry_run=False`를 명시적으로 전달해야만 실행됨.
  의도하지 않은 호출에서 시스템을 보호하는 "safe default" 패턴.

- **태그 기반 예외 처리**: `AllowPublic=true` 태그가 부여된 리소스는 조치 대상에서 제외.
  버킷 소유자가 자기 책임으로 태그를 부여하고, 자동화 코드는 그것을 신뢰. 권한과 책임의 자연스러운 분리.

- **detection-remediation 통합**: `/auto-remediate`가 점검 결과를 받아 위험 버킷만 선별 조치.
  단일 버킷용 `/remediate`와 같은 안전장치(dry-run, 태그 예외)를 일괄 처리에도 그대로 적용.

### 동작 확인

두 안전장치가 각각 독립적으로 작동하는지 검증했다.

| 조건 | 요청 | 결과 |
|---|---|---|
| 퍼블릭 액세스 블록 미설정 | `/s3-status` | 위험 감지 |
| 태그 없음 | `dry_run=true` | 조치하지 않고 적용 예정 사항만 반환 |
| `AllowPublic=true` 태그 있음 | `dry_run=false` | **조치하지 않고 제외** |
| 태그 제거 후 | `dry_run=false` | 퍼블릭 액세스 차단 적용 |

![조치 흐름](./docs/images/remediation-flow.png)

> 세 번째 항목이 핵심이다. 실제 조치를 요청(`dry_run=false`)했음에도 태그가 있는
> 버킷은 건너뛴다. 태그 예외는 dry-run 여부와 무관하게 독립적으로 적용된다.

## 준실시간 알림 시스템

S3 설정 변경이 발생하는 즉시 운영자에게 알림이 도착하는 이벤트 기반 시스템이다.
주기 점검에 의존하지 않고 변경 발생 시점에 인지할 수 있다.

- **이벤트 감지**: CloudTrail에 기록된 PutBucketPublicAccessBlock API 호출을 EventBridge가 준실시간으로 잡는다.
- **알림 처리**: Lambda 함수(Python 3.12)가 이벤트에서 버킷명, 변경자, 시간, 차단 상태를 추출하고 Slack 메시지로 보낸다.
- **외부 의존성 없음**: Lambda는 표준 라이브러리 `urllib`만 사용합니다. 외부 패키지 패키징 없이 동작한다.
- **민감 정보 관리**: Slack Webhook URL은 Terraform 변수(`terraform.tfvars`)로 분리하고 `.gitignore`로 유출 방지한다.
- **IaC**: 알림 시스템 전체 (Lambda, IAM Role, EventBridge 규칙, 권한)를 Terraform으로 정의했다.

![Slack 준실시간 알림 - 위험/안전 상태별 알림](./docs/images/slack_alert.png)

> 퍼블릭 액세스 변경 시 상태(위험/안전)에 따라 즉시 알림 전송

## Kubernetes 확장

기존 컴플라이언스 애플리케이션을 EKS에 배포하면서, "클라우드 네이티브 환경에서 안전하고 견고하게 운영되는 애플리케이션"이라는 관점을 더했다. 핵심은 단순 배포가 아니라 **권한을 최소한으로, 자격증명을 정적으로 남기지 않고, 배포 중 요청 손실을 없애는 것**이다.

### 정적 자격증명 제거 — 확인된 사실만 남긴다

이 프로젝트를 K8s로 확장하며 가장 먼저 만든 것은, 역설적으로 "잘못된 상태"였다. 애플리케이션 Secret에 AWS 액세스 키를 평문으로 심어두고, 이 상태가 왜 위험한지를 실제로 확인하는 것에서 시작했다.

```bash
kubectl get secret s3-monitor-secret -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d
# → 액세스 키가 그대로 출력된다. base64는 암호화가 아니다.
```

이 상태를 기준점(before)으로 두고, 다음 두 단계로 걷어냈다.

**① 전용 ServiceAccount — 안 쓰는 권한은 존재 자체가 위험**

애플리케이션이 실제로 Kubernetes API를 호출하는지부터 코드로 확인했다(`boto3`만 사용, K8s 클라이언트 의존성 없음). 불필요하다는 것이 확인되자, `default` ServiceAccount 대신 전용 SA를 만들고 토큰 자동 마운트 자체를 껐다.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: s3-monitor-sa
automountServiceAccountToken: false
```

적용 전후로 컨테이너 내부의 토큰 마운트 경로 자체가 사라지는 것을 확인했다 — 파일이 비는 게 아니라 마운트 지점 자체가 생성되지 않는다.

**② IRSA — 정적 키를 걷어내고 임시 자격증명으로 전환**

OIDC 기반 신뢰 체인(EKS OIDC issuer → IAM OIDC provider → IAM Role Trust Policy → STS)을 구성해, 전용 ServiceAccount가 특정 IAM Role만 assume할 수 있도록 제한했다.

```json
{
  "Effect": "Allow",
  "Principal": { "Federated": "<OIDC Provider ARN>" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "<oidc-provider>:sub": "system:serviceaccount:default:s3-monitor-sa",
      "<oidc-provider>:aud": "sts.amazonaws.com"
    }
  }
}
```

Permission Policy는 코드에서 실제로 호출하는 API만 grep으로 추출해 구성했다(`s3:ListAllMyBuckets`, `s3:GetBucketPublicAccessBlock`, `s3:PutBucketPublicAccessBlock`, `iam:ListUsers` 등 총 10개 액션, 서비스 단위 와일드카드 없음).

Secret을 완전히 제거한 뒤, 세 엔드포인트(`/s3-status`, `/iam-status`, `/trail-history`) 모두 정적 액세스 키 없이 정상 응답하는 것을 확인했다.

```bash
kubectl exec <pod> -- env | grep AWS
# AWS_ROLE_ARN=arn:aws:iam::<account>:role/s3-monitor-irsa-role
# AWS_WEB_IDENTITY_TOKEN_FILE=/var/run/secrets/eks.amazonaws.com/serviceaccount/token
# (AWS_ACCESS_KEY_ID 없음)
```

| 단계 | 인증 방식 | Secret 존재 여부 |
|---|---|---|
| Before | 정적 액세스 키 (Secret → 환경변수) | 있음 |
| After | IRSA (OIDC → STS 임시 자격증명) | **없음** |

### RBAC — 최소 권한을 설계 원칙이 아니라 검증된 사실로

애플리케이션이 필요로 하지 않는 권한은 부여하지 않는다는 원칙을, 가상 시나리오로 직접 검증했다. "Pod 상태 조회 기능이 추가된다면"이라는 가정 아래 Role을 설계하고, `kubectl auth can-i`로 권한 경계가 설계대로 동작하는지 확인했다.

```bash
kubectl auth can-i get pods --as=system:serviceaccount:default:s3-monitor-sa     # yes
kubectl auth can-i list pods --as=system:serviceaccount:default:s3-monitor-sa    # yes
kubectl auth can-i delete pods --as=system:serviceaccount:default:s3-monitor-sa  # no
```

검증이 끝난 뒤에는 실제 사용처가 없는 권한이므로 Role/RoleBinding을 클러스터에서 제거했다 — 필요할 때 확인하고, 필요 없으면 남기지 않는다는 원칙을 실습에도 그대로 적용했다.

### 컨테이너 보안 — securityContext

루트 권한 없이, 쓰기 불가능한 파일시스템에서, 최소한의 커널 권한으로 실행되도록 구성했다.

```yaml
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
```

`runAsNonRoot`는 Dockerfile에 숫자 UID(`USER 1000`)를 명시해야 적용 가능하다 — 문자열 사용자명은 kubelet이 사전에 검증할 수 없어 거부된다. `readOnlyRootFilesystem`은 코드가 로컬 디스크에 쓰기 작업을 하지 않는다는 것을 코드 검토와 실제 쓰기 시도(`touch` 거부 확인)로 검증한 뒤 적용했다.

### Pod 배포 중 요청 손실 제거 — 실측 기반 개선

배포·재시작 시 실제로 요청이 얼마나 유실되는지 외부에서 직접 계측하고, 원인을 구성 요소별로 분해해 단계적으로 개선했다.

| 개선 단계 | 다운타임 | 누적 개선율 |
|---|---|---|
| 0. 최초 상태 | ~7.95초 | - |
| 1. readinessProbe 재시도 주기 튜닝 (5s → 2s) | ~4.08초 | 49% |
| 2. + preStop hook (종료 유예 5초) | ~3.585초 | 55% |
| 3. + replicas 2, `maxUnavailable:0`/`maxSurge:1` | **0초** | **100%** |

핵심 원인은 컨테이너 자체의 기동 속도(1초 미만)가 아니라, **kubelet이 새 Pod를 Ready로 인식하기까지 readinessProbe의 재시도 간격에 걸리는 구조적 지연**이었다. `preStop`은 종료 유예 시간 동안 컨테이너가 계속 응답 가능한 상태를 유지해 Endpoint 갱신이 전파될 시간을 벌어준다 — 대기 시간이 늘어나는 것이 곧 사용자 체감 다운타임 증가를 의미하지 않는다는 것을 실측으로 확인했다.

`PodDisruptionBudget`(`minAvailable: 1`)으로 `kubectl drain` 시에도 최소 가용성이 보장되는 것을 검증했다. 다만 PDB는 명시적으로 보호 대상으로 지정한 리소스에만 적용된다 — 같은 클러스터의 PDB 없는 다른 컴포넌트(Ingress Controller 등)는 여전히 보호되지 않으므로, 애플리케이션 자체의 가용성과 그 앞단 경로의 가용성은 별도로 챙겨야 한다는 것도 확인했다.

### HPA — CPU 기준 자동 스케일링

```yaml
minReplicas: 2
maxReplicas: 5
metrics:
  - type: Resource
    resource: {name: cpu, target: {type: Utilization, averageUtilization: 50}}
```

부하 발생 시 약 1분 내 최대치까지 스케일 아웃, 부하 해소 후에는 `stabilizationWindowSeconds`(기본 300초) 동안 대기한 뒤 스케일 인 — 트래픽 출렁임에 의한 반복적 스케일링(flapping)을 방지하는 의도된 비대칭 동작임을 실측으로 확인했다.

### Helm — 환경별 배포 관리

Kustomize의 patch 기반 관리를 Helm 템플릿 기반으로 전환했다. 공통 설정(`values.yaml`)과 환경별 오버라이드(`values-kind.yaml`, `values-eks.yaml`)로 분리한다.

```bash
helm install s3-monitor helm/s3-monitor -f helm/s3-monitor/values.yaml -f helm/s3-monitor/values-kind.yaml
```

계정 ID 등 민감 정보가 담긴 `values-eks.yaml`은 `.gitignore` 처리하고 `values-eks.yaml.example`로 형식만 공유한다. Kustomize 구성(`k8s/`)은 참고용으로 병행 유지한다 — [k8s/README.md](./k8s/README.md) 참고.

### ArgoCD — GitOps 배포

Git 저장소의 매니페스트 상태를 클러스터가 계속 따라가도록 ArgoCD로 구성했다.

```bash
kubectl apply -f argocd/s3-monitor-app.yaml
```

`selfHeal: true`로 수동 변경을 감지해 자동으로 Git 상태로 되돌리는 것을 확인했다. 다만 HPA가 관리하는 `replicas` 필드와 ArgoCD의 동기화가 충돌하는 것을 발견해, `ignoreDifferences`로 해당 필드를 ArgoCD 감시 대상에서 제외했다 — 여러 컨트롤러가 같은 필드를 관리하려 할 때는 소유권을 명시적으로 분리해야 한다는 것을 실제로 겪었다.

## 기술 스택

- Terraform : 인프라의 코드화 및 버전 관리 (IaC) — S3/알림 인프라 및 EKS 클러스터(`terraform-eks/`)
- Trivy : 유지보수가 중단된 tfsec의 기능을 흡수한, 배포 전 환경 취약점을 확인하는 보안 스캐너. 스캔 결과는 `terraform-s3-security/reports/`(IaC)와 `reports/`(컨테이너 이미지·EKS) 참고
- boto3 : 파이썬 코드만으로 AWS 서비스 상태를 점검하고 안전하게 조치
- CloudTrail : AWS 서비스의 API 호출 이력을 기록해 설정 변경 추적
- FastAPI : 점검 결과를 API 엔드포인트로 제공
- Docker : 애플리케이션 컨테이너화 (이식성, 환경 격리)
- EventBridge : CloudTrail 이벤트 기반 준실시간 알림 트리거
- Lambda : 알림 메시지 포맷팅 및 Slack 전송 (Python, 외부 의존성 없음)
- Slack Incoming Webhook : 운영자에게 준실시간 알림 채널
- Kubernetes (EKS) : 컨테이너 오케스트레이션, RBAC 기반 최소 권한 관리
- Helm : 환경별(kind/EKS) 배포 설정을 values 파일로 관리 (정식 배포 방식)
- Kustomize : base+overlay 기반 환경 분리 (참고용, 병행 유지)
- ArgoCD : GitOps 기반 선언적 배포, Git 상태와 클러스터 상태 자동 동기화
- IRSA (IAM Roles for Service Accounts) : OIDC 기반 임시 자격증명, 정적 액세스 키 제거
- ECR : 컨테이너 이미지 레지스트리
- metrics-server / HPA : CPU 사용률 기반 자동 스케일링

## 실행 방법

### Docker로 실행 (로컬 단일 컨테이너)

```bash
# 이미지 빌드
docker build -t s3-monitor .

# 컨테이너 실행 (AWS 자격증명 마운트)
docker run -v ${HOME}/.aws:/root/.aws -p 8000:8000 s3-monitor

# 브라우저에서 http://localhost:8000/docs 접속
```

AWS 자격증명은 호스트의 `~/.aws/` 폴더를 컨테이너에 마운트하는 방식으로 전달한다. 이 방식은 로컬 개발용이며, K8s 환경에서는 아래와 같이 IRSA로 대체했다.

### Kubernetes로 실행 (Helm, 정식 배포 방식)

```bash
# 로컬 kind 클러스터
kind create cluster --config k8s/tmp/kind-calico.yaml
helm install s3-monitor helm/s3-monitor -f helm/s3-monitor/values.yaml -f helm/s3-monitor/values-kind.yaml

# EKS (사전에 terraform-eks/ 로 클러스터 프로비저닝 필요)
aws eks update-kubeconfig --name <cluster-name> --region <region>
helm install s3-monitor helm/s3-monitor -f helm/s3-monitor/values.yaml -f helm/s3-monitor/values-eks.yaml
```

EKS 환경에서는 정적 자격증명 없이 IRSA를 통해 AWS API를 호출한다. `~/.aws` 마운트나 액세스 키 발급이 필요 없다.

### ArgoCD로 배포 (GitOps)

```bash
kubectl apply -f argocd/s3-monitor-app.yaml
```

이후 클러스터 배포는 Git push를 통해서만 이루어지며, ArgoCD가 자동으로 감지해 동기화한다.

## 한계 및 개선 계획

| 항목 | 현재 | 개선 방향 |
|---|---|---|
| 인증 | API 엔드포인트에 인증 계층 없음 | API Key 또는 IAM 기반 인증 계층 추가 |
| Lambda 실패 처리 | 재시도·DLQ 미구성 | SQS DLQ 연결 후 실패 이벤트 보존 |
| 탐지 지연 | CloudTrail 기록까지 수 분 소요 | 즉시성이 필요하면 S3 이벤트 알림 직접 구독 검토 |
| 페이지네이션 | 버킷·사용자 목록 미처리 | boto3 Paginator 적용 |
| Terraform state | S3 애플리케이션은 로컬 파일, EKS도 로컬 파일 | S3 원격 backend로 전환 (3-tier에는 적용 완료) |
| 태그 예외 처리 | `AllowPublic=true` 부여만으로 조치 제외 | 태그 부여 이력을 CloudTrail로 별도 감사 |
| IAM 조치 권한 범위 | `s3:PutBucketPublicAccessBlock`이 계정 전체(`Resource: "*"`) | 조치 대상 버킷을 태그 기반으로 스코핑 (CSPM 확장에서 다룰 예정) |
| Egress 정책 | NetworkPolicy가 Ingress 방향만 제한, Egress는 무제한 | VPC Endpoint(S3/STS/IAM/CloudTrail)로 AWS API 트래픽을 경로 자체를 좁힌 뒤 NetworkPolicy egress 규칙 적용 |
| Ingress Controller 가용성 | 단일 노드 kind에서 hostPort 제약으로 replicas 확장 불가(SPOF) | EKS(멀티 노드)에서 재검증 예정 |
| EKS 배포 자동화 | Terraform은 완전 자동, `helm install`은 수동 실행 | CI/CD 파이프라인의 Secrets 저장소에서 배포 시점에 값을 주입하는 방식으로 완전 자동화 검토 |
| 관측·비용 가시성 | Container Insights 검증 완료(일시적 활성화, 상시 미운영) | 상시 운영 여부 및 프로젝트별 비용 분리를 위한 태그 체계 검토 |
| API 에러 처리 일관성 | `/s3-status` 등 일부 엔드포인트가 AWS 인증 실패 시 500을 그대로 노출 | 예외 처리 통일, 503 등 적절한 상태 코드로 정리 |

