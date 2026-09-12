# k8s/ — Kustomize 기반 배포 (참고용)

이 디렉토리는 Week 3~4에서 사용한 Kustomize 기반 K8s 매니페스트다.

**Week 5부터 정식 배포 방식은 [`../helm/s3-monitor/`](../helm/s3-monitor/)의 Helm 차트다.**
이 디렉토리(`k8s/`)는 삭제하지 않고 유지하는데, 이유는 다음과 같다.

- 동일한 애플리케이션을 Kustomize(patch 기반)와 Helm(템플릿 기반) 두 방식으로
  배포 가능하게 관리해본 경험을 코드로 남기기 위함
- Week 3~4의 실측(다운타임 개선, RBAC, IRSA, HPA 등)이 이 구조 위에서
  이루어졌으므로, 그 과정의 원본 맥락을 보존하기 위함

## 구조

```
k8s/
├── base/           환경 공통 매니페스트 (EKS 기준값)
├── overlays/
│   ├── kind/        로컬 개발용 patch (image, readinessProbe.path)
│   └── eks/          EKS용 patch (ECR image, IRSA role-arn)
├── experiments/     학습 실습 후 클러스터에는 미적용된 것들 (RBAC 최소권한 실습,
│                     ingress-nginx PDB 시도 등, 각 파일 상단에 배경 설명 주석 있음)
└── tmp/              kind 클러스터 설정 등 임시 파일
```

## 실행 방법 (참고용, 현재는 Helm 사용 권장)

```bash
kubectl apply -k k8s/overlays/kind   # 로컬
kubectl apply -k k8s/overlays/eks    # EKS
```

Kustomize와 Helm을 동시에 클러스터에 적용하면 리소스 이름 충돌이 발생한다
(둘 다 `s3-monitor`라는 이름으로 Deployment 등을 만들기 때문).
둘 중 하나만 클러스터에 적용된 상태를 유지할 것 — 전환 시 `kubectl delete -k k8s/overlays/<env>` 후 `helm install`.