# Deployment Guide

This guide covers deploying Remembr to production environments including Railway, Docker, Docker Compose, and Kubernetes.

---

## Table of Contents

1. [Deployment Options](#deployment-options)
2. [Railway Deployment](#railway-deployment)
3. [Docker Deployment](#docker-deployment)
4. [Docker Compose Deployment](#docker-compose-deployment)
5. [PgBouncer Connection Pooling](#pgbouncer-connection-pooling)
6. [Kubernetes Deployment](#kubernetes-deployment)
7. [Environment Configuration](#environment-configuration)
8. [Database Setup](#database-setup)
9. [Monitoring & Scaling](#monitoring--scaling)
10. [Security Checklist](#security-checklist)

---

## Deployment Options

### Quick Comparison

| Option | Best For | Complexity | Cost | Scale |
|--------|----------|------------|------|-------|
| **Railway** | Quick start, MVP | Low | $5-50/mo | Low-Medium |
| **Docker** | Single server | Medium | Variable | Low |
| **Docker Compose** | Development, small teams | Medium | Variable | Low-Medium |
| **Kubernetes** | Enterprise, high scale | High | Variable | High |

### Architecture Overview

```mermaid
graph TB
    subgraph "Client Layer"
        SDK[SDK/Adapters]
    end
    
    subgraph "Deployment Platform"
        LB[Load Balancer]
        API1[API Instance 1]
        API2[API Instance 2]
        APIN[API Instance N]
    end
    
    subgraph "Managed Services"
        PG[(PostgreSQL<br/>+ pgvector)]
        REDIS[(Redis)]
        JINA[Jina AI<br/>Embeddings]
    end
    
    subgraph "Monitoring"
        LOGS[Logs]
        METRICS[Metrics]
        ALERTS[Alerts]
    end
    
    SDK --> LB
    LB --> API1
    LB --> API2
    LB --> APIN
    
    API1 --> PG
    API1 --> REDIS
    API1 --> JINA
    
    API2 --> PG
    API2 --> REDIS
    API2 --> JINA
    
    APIN --> PG
    APIN --> REDIS
    APIN --> JINA
    
    API1 --> LOGS
    API2 --> LOGS
    APIN --> LOGS
    
    LOGS --> METRICS
    METRICS --> ALERTS
    
    style LB fill:#4A90E2
    style PG fill:#336791
    style REDIS fill:#DC382D
    style JINA fill:#FF6B6B
```

---

## Railway Deployment

### Prerequisites

- GitHub account with repository access
- Railway account (https://railway.app)
- Supabase account (https://supabase.com)
- Upstash account (https://upstash.com)
- Jina AI API key (https://jina.ai)

### Railway Architecture

```
Railway (API Server)
├── Supabase (PostgreSQL + pgvector)
├── Upstash (Redis)
└── Sentry (Error Tracking - Optional)
```

## 1. Set Up Supabase Database

### Create Project

1. Go to https://supabase.com/dashboard
2. Click "New Project"
3. Choose organization and set:
   - Name: `remembr-production` (or `remembr-staging`)
   - Database Password: Generate a strong password
   - Region: Choose closest to your users
4. Wait for project to be provisioned (~2 minutes)

### Enable pgvector Extension

1. In your Supabase project, go to "SQL Editor"
2. Run this SQL command:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
3. Verify with:
```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

### Get Connection String

1. Go to "Project Settings" → "Database"
2. Find "Connection string" section
3. Copy the "URI" format (not "Transaction" pooler)
4. It looks like:
```
postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
```

## 2. Set Up Upstash Redis

### Create Database

1. Go to https://console.upstash.com
2. Click "Create Database"
3. Configure:
   - Name: `remembr-production` (or `remembr-staging`)
   - Type: Regional (or Global for multi-region)
   - Region: Choose closest to your Railway deployment
   - TLS: Enabled (recommended)
4. Click "Create"

### Get Connection String

1. In your database dashboard, find "REST API" section
2. Copy the "Redis URL" (starts with `redis://` or `rediss://`)
3. Format:
```
rediss://default:[PASSWORD]@[ENDPOINT]:6379
```

## 3. Deploy to Railway

### Create Railway Project

1. Go to https://railway.app/dashboard
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub account
5. Select the `remembr` repository
6. Railway will detect the `railway.toml` configuration

### Configure Environment Variables

In Railway project settings, add these environment variables:

#### Required Variables

```bash
# Database (from Supabase)
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres

# Redis (from Upstash)
REDIS_URL=rediss://default:[PASSWORD]@[ENDPOINT]:6379

# JWT Authentication
SECRET_KEY=<generate-with-openssl-rand-hex-32>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Environment
ENVIRONMENT=production

# Jina AI Embeddings
JINA_API_KEY=<your-jina-api-key>
JINA_EMBEDDING_MODEL=jina-embeddings-v3

# Logging
LOG_LEVEL=INFO
```

#### Optional Variables

```bash
# Sentry (Error Tracking)
SENTRY_DSN=<your-sentry-dsn>
```

### Generate SECRET_KEY

Run locally:
```bash
openssl rand -hex 32
```

Or use Python:
```python
import secrets
print(secrets.token_hex(32))
```

### Deploy

1. Railway will automatically deploy after environment variables are set
2. Monitor deployment logs in Railway dashboard
3. Once deployed, Railway provides a public URL like:
   ```
   https://remembr-production.up.railway.app
   ```

### Verify Deployment

Test the health endpoint:
```bash
curl https://your-app.up.railway.app/api/v1/health
```

Expected response:
```json
{
  "status": "ok",
  "environment": "production",
  "version": "0.1.0"
}
```

## 4. Set Up Custom Domain (Optional)

### In Railway

1. Go to your service settings
2. Click "Settings" → "Domains"
3. Click "Generate Domain" or "Custom Domain"
4. For custom domain:
   - Enter your domain (e.g., `api.remembr.com`)
   - Add the CNAME record to your DNS provider
   - Wait for DNS propagation (~5-60 minutes)

### Update CORS Settings

If using a custom domain, update CORS in `server/app/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Update this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 5. Staging vs Production Setup

### Recommended Approach

Create two separate Railway projects:

#### Staging Environment

- **Project Name**: `remembr-staging`
- **Branch**: Deploy from `develop` or `staging` branch
- **Database**: Separate Supabase project (`remembr-staging`)
- **Redis**: Separate Upstash database (`remembr-staging`)
- **Environment Variable**: `ENVIRONMENT=staging`
- **Purpose**: Testing before production deployment

#### Production Environment

- **Project Name**: `remembr-production`
- **Branch**: Deploy from `main` branch only
- **Database**: Production Supabase project (`remembr-production`)
- **Redis**: Production Upstash database (`remembr-production`)
- **Environment Variable**: `ENVIRONMENT=production`
- **Purpose**: Live user-facing API

### Branch-Based Deployment

Configure in Railway:
1. Go to project settings
2. Under "Source" → "Branch"
3. Set staging to deploy from `develop`
4. Set production to deploy from `main`

## 6. Database Migrations

### Run Migrations on Railway

After deployment, run Alembic migrations:

1. In Railway dashboard, go to your service
2. Click "Settings" → "Variables"
3. Ensure `DATABASE_URL` is set
4. Use Railway CLI or add a migration job:

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to project
railway link

# Run migrations
railway run alembic upgrade head
```

Or add a one-time deployment command in Railway:
```bash
alembic upgrade head && uvicorn server.app.main:app --host 0.0.0.0 --port $PORT
```

## 7. Monitoring and Logs

### Railway Logs

- View real-time logs in Railway dashboard
- Logs are structured JSON (from loguru)
- Filter by log level, request ID, etc.

### Sentry Integration

If `SENTRY_DSN` is configured:
1. All errors automatically reported to Sentry
2. View errors at https://sentry.io
3. Get alerts for new errors
4. Track error frequency and impact

### Health Checks

Railway automatically monitors `/api/v1/health`:
- Checks every 30 seconds
- Restarts service if unhealthy
- Configurable in `railway.toml`

## 8. Scaling

### Vertical Scaling

In Railway:
1. Go to service settings
2. Adjust resources (CPU, Memory)
3. Railway automatically restarts with new resources

### Horizontal Scaling

For high traffic:
1. Enable multiple replicas in Railway
2. Railway handles load balancing automatically
3. Ensure your app is stateless (uses Redis for sessions)

## 9. Rollback

### Via Railway Dashboard

1. Go to "Deployments"
2. Find previous successful deployment
3. Click "Redeploy"

### Via Git

```bash
# Revert to previous commit
git revert HEAD
git push origin main

# Railway auto-deploys the reverted version
```

## 10. Cost Estimation

### Staging Environment

- Railway: $5-10/month (Hobby plan)
- Supabase: Free tier (up to 500MB database)
- Upstash: Free tier (10K commands/day)
- **Total**: ~$5-10/month

### Production Environment

- Railway: $20-50/month (depends on usage)
- Supabase: $25/month (Pro plan with more resources)
- Upstash: $10-30/month (depends on usage)
- Sentry: Free tier or $26/month (Team plan)
- **Total**: ~$55-130/month

## Troubleshooting

### Deployment Fails

Check Railway logs for errors:
- Missing environment variables
- Database connection issues
- Port binding problems

### Database Connection Errors

- Verify `DATABASE_URL` is correct
- Check Supabase project is running
- Ensure IP allowlist includes Railway (usually not needed)
- Test connection locally with same URL

### Redis Connection Errors

- Verify `REDIS_URL` format is correct
- Check Upstash database is active
- Ensure TLS is enabled if using `rediss://`

### Health Check Failing

- Verify `/api/v1/health` endpoint works locally
- Check if app is binding to `0.0.0.0` not `127.0.0.1`
- Ensure `$PORT` environment variable is used

## Security Checklist

- [ ] `SECRET_KEY` is randomly generated and unique per environment
- [ ] Database passwords are strong and rotated regularly
- [ ] `ENVIRONMENT=production` is set in production
- [ ] API documentation (`/docs`) is disabled in production
- [ ] CORS origins are restricted to your domains
- [ ] Sentry DSN is configured for error tracking
- [ ] All secrets are stored in Railway environment variables, not in code
- [ ] `.env` files are in `.gitignore`

---

## Docker Deployment

### Single Container Deployment

**Dockerfile** (already included in repository):
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY server/ ./server/
COPY sdk/python/ ./sdk/python/

# Install SDK
RUN pip install -e ./sdk/python

WORKDIR /app/server

# Run migrations and start server
CMD alembic upgrade head && \
    uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Build and Run

```bash
# Build image
docker build -t remembr:latest .

# Run container
docker run -d \
  --name remembr-api \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://..." \
  -e REDIS_URL="redis://..." \
  -e SECRET_KEY="your-secret-key" \
  -e JINA_API_KEY="your-jina-key" \
  remembr:latest

# View logs
docker logs -f remembr-api

# Stop container
docker stop remembr-api
```

---

## Docker Compose Deployment

### Full Stack with Docker Compose

**docker-compose.yml**:
```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg15
    environment:
      POSTGRES_DB: remembr
      POSTGRES_USER: remembr
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U remembr"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://remembr:${DB_PASSWORD}@postgres:5432/remembr
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      SECRET_KEY: ${SECRET_KEY}
      JINA_API_KEY: ${JINA_API_KEY}
      ENVIRONMENT: production
      LOG_LEVEL: INFO
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  postgres_data:
  redis_data:
```

### Deploy with Docker Compose

```bash
# Create .env file
cat > .env << EOF
DB_PASSWORD=$(openssl rand -hex 16)
REDIS_PASSWORD=$(openssl rand -hex 16)
SECRET_KEY=$(openssl rand -hex 32)
JINA_API_KEY=your-jina-api-key
EOF

# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

---

## PgBouncer Connection Pooling

### Why PgBouncer?

FastAPI + asyncpg can open many concurrent database connections — one per active request. PostgreSQL handles each connection with a dedicated OS process, so 200 simultaneous API requests would create 200 PostgreSQL processes. This wastes memory and degrades performance.

PgBouncer sits between the application and PostgreSQL, multiplexing many client connections onto a small pool of real database connections. In **transaction mode**, PgBouncer assigns a real connection for the duration of a single transaction, then releases it back to the pool immediately. This lets 200+ clients share just 20 real PostgreSQL connections.

### Docker Compose configuration

The included `docker-compose.yml` runs `edoburu/pgbouncer` with:

| Setting | Value | Notes |
|---------|-------|-------|
| `POOL_MODE` | `transaction` | Highest multiplexing; connection returned after each transaction |
| `DEFAULT_POOL_SIZE` | `20` | Real connections to PostgreSQL per database/user pair |
| `MAX_CLIENT_CONN` | `200` | Max simultaneous clients connecting to PgBouncer |
| `AUTH_TYPE` | `md5` | Client authentication mode; upgrade to `scram-sha-256` in production |

The server's `DATABASE_URL` points to PgBouncer (`pgbouncer:6432`) rather than PostgreSQL directly.

### Session.py compatibility

Transaction-mode pooling has one important constraint: **prepared statements cannot persist across transactions** because a different real connection may serve the next transaction. Remembr's `session.py` automatically detects PgBouncer in the URL and:

1. Uses `NullPool` — SQLAlchemy does not maintain its own pool; PgBouncer is the pool.
2. Passes `statement_cache_size=0` and `prepared_statement_cache_size=0` to asyncpg, disabling asyncpg's prepared statement cache.

This detection is automatic. If you route through PgBouncer via a different hostname, set `USE_PGBOUNCER=true` in your environment.

### Production tuning

```bash
# Tune for your workload — these are in the pgbouncer environment block:
DEFAULT_POOL_SIZE=50          # if you have many DB cores available
MAX_CLIENT_CONN=500           # if you run many API replicas
POOL_MODE=session             # if you use PostgreSQL features that break in transaction mode
                              # (e.g., advisory locks, LISTEN/NOTIFY, temp tables)
```

For production, also set:
- `AUTH_TYPE=scram-sha-256` (requires pgbouncer 1.14+)
- `SERVER_TLS_SSLMODE=require` if PostgreSQL TLS is enabled
- Mount a custom `pgbouncer.ini` for advanced options

### Bypassing PgBouncer

To connect directly (e.g., for `alembic upgrade head` which uses DDL):

```bash
DATABASE_URL=postgresql+asyncpg://remembr:remembr@localhost:5432/remembr \
  docker compose exec server alembic upgrade head
```

Alembic migrations should run against PostgreSQL directly (not through PgBouncer in transaction mode) because DDL statements and schema changes are incompatible with transaction-mode pooling.

---

## Kubernetes Deployment

### Kubernetes Architecture

```mermaid
graph TB
    subgraph "Ingress"
        ING[Ingress Controller<br/>NGINX/Traefik]
    end
    
    subgraph "Kubernetes Cluster"
        subgraph "API Deployment"
            API1[API Pod 1]
            API2[API Pod 2]
            API3[API Pod N]
        end
        
        SVC[Service<br/>ClusterIP]
        
        subgraph "StatefulSets"
            PG[PostgreSQL<br/>StatefulSet]
            REDIS[Redis<br/>StatefulSet]
        end
        
        subgraph "Storage"
            PVC1[PVC - Postgres]
            PVC2[PVC - Redis]
        end
    end
    
    ING --> SVC
    SVC --> API1
    SVC --> API2
    SVC --> API3
    
    API1 --> PG
    API2 --> PG
    API3 --> PG
    
    API1 --> REDIS
    API2 --> REDIS
    API3 --> REDIS
    
    PG --> PVC1
    REDIS --> PVC2
    
    style ING fill:#4A90E2
    style SVC fill:#50C878
    style PG fill:#336791
    style REDIS fill:#DC382D
```

### Kubernetes Manifests

**namespace.yaml**:
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: remembr
```

**configmap.yaml**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: remembr-config
  namespace: remembr
data:
  ENVIRONMENT: "production"
  LOG_LEVEL: "INFO"
  JINA_EMBEDDING_MODEL: "jina-embeddings-v3"
```

**secret.yaml**:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: remembr-secrets
  namespace: remembr
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:pass@postgres:5432/remembr"
  REDIS_URL: "redis://:pass@redis:6379/0"
  SECRET_KEY: "your-secret-key"
  JINA_API_KEY: "your-jina-key"
```

**deployment.yaml**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: remembr-api
  namespace: remembr
spec:
  replicas: 3
  selector:
    matchLabels:
      app: remembr-api
  template:
    metadata:
      labels:
        app: remembr-api
    spec:
      containers:
      - name: api
        image: remembr:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: remembr-config
        - secretRef:
            name: remembr-secrets
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

**service.yaml**:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: remembr-api
  namespace: remembr
spec:
  selector:
    app: remembr-api
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: ClusterIP
```

**ingress.yaml**:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: remembr-ingress
  namespace: remembr
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.remembr.com
    secretName: remembr-tls
  rules:
  - host: api.remembr.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: remembr-api
            port:
              number: 80
```

### Deploy to Kubernetes

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create secrets (use your actual values)
kubectl create secret generic remembr-secrets \
  --from-literal=DATABASE_URL="postgresql://..." \
  --from-literal=REDIS_URL="redis://..." \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=JINA_API_KEY="your-key" \
  -n remembr

# Apply configurations
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# Check status
kubectl get pods -n remembr
kubectl get svc -n remembr
kubectl get ingress -n remembr

# View logs
kubectl logs -f deployment/remembr-api -n remembr

# Scale deployment
kubectl scale deployment remembr-api --replicas=5 -n remembr
```

---

## Environment Configuration

### Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | - | PostgreSQL connection string |
| `REDIS_URL` | Yes | - | Redis connection string |
| `SECRET_KEY` | Yes | - | JWT signing key (32+ chars) |
| `JINA_API_KEY` | Yes | - | Jina AI API key for embeddings |
| `ENVIRONMENT` | No | `development` | Environment name |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `JINA_EMBEDDING_MODEL` | No | `jina-embeddings-v3` | Jina model name |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | JWT access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `7` | JWT refresh token TTL |
| `RATE_LIMIT_ENABLED` | No | `true` | Enable rate limiting |
| `RATE_LIMIT_REQUESTS` | No | `1000` | Requests per window |
| `RATE_LIMIT_WINDOW` | No | `60` | Rate limit window (seconds) |
| `SENTRY_DSN` | No | - | Sentry error tracking DSN |
| `CORS_ORIGINS` | No | `["*"]` | Allowed CORS origins |

### Generate Secrets

```bash
# Generate SECRET_KEY
openssl rand -hex 32

# Or with Python
python -c "import secrets; print(secrets.token_hex(32))"

# Generate strong passwords
openssl rand -base64 32
```

---

## Database Setup

### PostgreSQL with pgvector

**Enable pgvector extension**:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**Run migrations**:
```bash
# Using Alembic
alembic upgrade head

# Or in Docker
docker exec remembr-api alembic upgrade head

# Or in Kubernetes
kubectl exec -it deployment/remembr-api -n remembr -- alembic upgrade head
```

### Database Backup

```bash
# Backup PostgreSQL
pg_dump -h localhost -U remembr -d remembr > backup.sql

# Restore PostgreSQL
psql -h localhost -U remembr -d remembr < backup.sql

# Backup with Docker
docker exec postgres pg_dump -U remembr remembr > backup.sql

# Restore with Docker
docker exec -i postgres psql -U remembr remembr < backup.sql
```

---

## Monitoring & Scaling

### Health Checks

```bash
# API health
curl https://your-api.com/api/v1/health

# Database health
curl https://your-api.com/api/v1/health/ready
```

### Metrics to Monitor

- **Request rate** (req/s)
- **Response time** (p50, p95, p99)
- **Error rate** (%)
- **Database connections**
- **Redis memory usage**
- **CPU and memory usage**

### Horizontal Scaling

**Railway**:
- Enable multiple replicas in settings
- Railway handles load balancing

**Docker Compose**:
```bash
docker-compose up -d --scale api=3
```

**Kubernetes**:
```bash
kubectl scale deployment remembr-api --replicas=5 -n remembr

# Or use HPA (Horizontal Pod Autoscaler)
kubectl autoscale deployment remembr-api \
  --cpu-percent=70 \
  --min=3 \
  --max=10 \
  -n remembr
```

### Vertical Scaling

Adjust resource limits in deployment configuration:
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

---

## Security Checklist

### Pre-Deployment

- [ ] `SECRET_KEY` is randomly generated (32+ characters)
- [ ] Database passwords are strong (16+ characters)
- [ ] All secrets stored in environment variables, not code
- [ ] `.env` files are in `.gitignore`
- [ ] API keys have appropriate scopes and expiration

### Production Configuration

- [ ] `ENVIRONMENT=production` is set
- [ ] `LOG_LEVEL=INFO` or `WARNING` (not `DEBUG`)
- [ ] API documentation (`/docs`) is disabled
- [ ] CORS origins are restricted to your domains
- [ ] Rate limiting is enabled
- [ ] TLS/HTTPS is enforced

### Database Security

- [ ] PostgreSQL uses strong password
- [ ] Database is not publicly accessible
- [ ] Row-level security (RLS) is enabled
- [ ] Regular backups are configured
- [ ] Connection pooling is configured

### Monitoring & Alerts

- [ ] Error tracking (Sentry) is configured
- [ ] Health checks are enabled
- [ ] Alerts for high error rates
- [ ] Alerts for high latency
- [ ] Alerts for service downtime

---

## Troubleshooting

### Common Issues

**Database Connection Errors**:
```bash
# Test connection
psql $DATABASE_URL

# Check if pgvector is installed
psql $DATABASE_URL -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

**Redis Connection Errors**:
```bash
# Test connection
redis-cli -u $REDIS_URL ping

# Check Redis info
redis-cli -u $REDIS_URL info
```

**Migration Errors**:
```bash
# Check current version
alembic current

# View migration history
alembic history

# Downgrade one version
alembic downgrade -1

# Upgrade to latest
alembic upgrade head
```

**Port Binding Issues**:
- Ensure app binds to `0.0.0.0` not `127.0.0.1`
- Use `$PORT` environment variable in containers
- Check if port is already in use: `lsof -i :8000`

---

## Cost Estimation

### Small Scale (< 1K users)

| Service | Provider | Cost/Month |
|---------|----------|------------|
| API Server | Railway Hobby | $5-10 |
| PostgreSQL | Supabase Free | $0 |
| Redis | Upstash Free | $0 |
| **Total** | | **$5-10** |

### Medium Scale (1K-10K users)

| Service | Provider | Cost/Month |
|---------|----------|------------|
| API Server | Railway Pro | $20-50 |
| PostgreSQL | Supabase Pro | $25 |
| Redis | Upstash | $10-30 |
| Monitoring | Sentry Team | $26 |
| **Total** | | **$81-131** |

### Large Scale (10K+ users)

| Service | Provider | Cost/Month |
|---------|----------|------------|
| API Server | Kubernetes (3 nodes) | $150-300 |
| PostgreSQL | Managed (RDS/Cloud SQL) | $100-500 |
| Redis | Managed (ElastiCache) | $50-200 |
| Monitoring | Datadog/New Relic | $100-500 |
| **Total** | | **$400-1500** |

---

## Support

For deployment assistance:
- **GitHub Issues**: [Report deployment issues](https://github.com/emartai/remembr/issues)
- **Email**: [nwangumaemmanuel29@gmail.com](mailto:nwangumaemmanuel29@gmail.com)
- **Documentation**: [docs/](docs/)

---

**Last Updated**: February 25, 2026  
**Maintainer**: [Emmanuel Nwanguma](https://linkedin.com/in/nwangumaemmanuel)
