# Kubernetes Deployment

This is a minimal, working baseline that runs the API and workers against external Postgres, Redis, and Ollama-compatible embeddings.

## ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: remembr-config
data:
  EMBEDDING_PROVIDER: "ollama"
  OLLAMA_BASE_URL: "http://ollama.default.svc.cluster.local:11434"
  OLLAMA_EMBEDDING_MODEL: "nomic-embed-text"
```

## Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: remembr-secrets
type: Opaque
stringData:
  DATABASE_URL: postgresql+asyncpg://remembr:remembr@postgres.default.svc.cluster.local:5432/remembr
  REDIS_URL: redis://redis.default.svc.cluster.local:6379
  SECRET_KEY: replace-me
```

## API Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: remembr-server
spec:
  replicas: 1
  selector:
    matchLabels:
      app: remembr-server
  template:
    metadata:
      labels:
        app: remembr-server
    spec:
      containers:
        - name: server
          image: ghcr.io/ai-emart/remembr-server:latest
          command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: remembr-config
            - secretRef:
                name: remembr-secrets
```

## Worker Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: remembr-worker
spec:
  replicas: 1
  selector:
    matchLabels:
      app: remembr-worker
  template:
    metadata:
      labels:
        app: remembr-worker
    spec:
      containers:
        - name: worker
          image: ghcr.io/ai-emart/remembr-server:latest
          command: ["celery", "-A", "app.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
          envFrom:
            - configMapRef:
                name: remembr-config
            - secretRef:
                name: remembr-secrets
```

## Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: remembr-server
spec:
  selector:
    app: remembr-server
  ports:
    - port: 80
      targetPort: 8000
```

Run migrations before routing production traffic.

