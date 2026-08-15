# SoldierIQ Docker Deployment Guide

## Quick Start

### 1. Setup Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your actual values
nano .env
```

**Important:** Fill in all required API keys and credentials in `.env`

### 2. Build and Run with Docker Compose

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### 3. Access the Application

- **Frontend**: http://localhost
- **Backend API**: http://localhost:8001
- **API Docs**: http://localhost:8001/docs

## Building Individual Services

### Backend

```bash
cd backend

# Build
docker build -t soldieriq-backend .

# Run
docker run -d \
  --name soldieriq-backend \
  -p 8001:8001 \
  --env-file ../.env \
  soldieriq-backend
```

### Frontend

```bash
cd frontend

# Build (pass environment variables at build time)
docker build \
  --build-arg VITE_API_URL=http://localhost:8001 \
  -t soldieriq-frontend .

# Run
docker run -d \
  --name soldieriq-frontend \
  -p 80:80 \
  soldieriq-frontend
```

## Environment Variables

### Backend Variables (Required)

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | JWT secret key | `your-secret-key` |
| `MONGODB_URL` | MongoDB connection string | `mongodb://localhost:27017` |
| `MONGODB_DATABASE` | Database name | `soldieriq` |
| `PINECONE_API_KEY` | Pinecone API key | `pcsk_xxx` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-xxx` |
| `IDRIVEE2_ACCESS_KEY_ID` | iDrive E2 access key | `xxx` |
| `IDRIVEE2_SECRET_ACCESS_KEY` | iDrive E2 secret | `xxx` |

### Frontend Variables (Build-time)

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_URL` | Backend API URL | `http://localhost:8001` |

**Note:** Frontend variables must be passed at **BUILD TIME** using `--build-arg` because Vite embeds them during the build process.

## Production Deployment

### Using Docker Compose (Recommended)

```bash
# Set production environment
export ENVIRONMENT=production

# Build with production settings
docker-compose build

# Start services
docker-compose up -d

# Check health
docker-compose ps
```

### Environment-Specific Configurations

Create separate `.env` files for different environments:

```bash
.env.development
.env.staging
.env.production
```

Then load the appropriate file:

```bash
# Development
docker-compose --env-file .env.development up -d

# Production
docker-compose --env-file .env.production up -d
```

## Health Checks

Both services include health checks:

- **Backend**: `http://localhost:8001/api/health`
- **Frontend**: `http://localhost/health`

Check container health:

```bash
docker ps
# Look for "healthy" status
```

## Troubleshooting

### Backend won't start

```bash
# Check logs
docker-compose logs backend

# Common issues:
# - Missing environment variables
# - Database connection failed
# - Port 8001 already in use
```

### Frontend shows blank page

```bash
# Verify environment variables were passed at build time
docker inspect soldieriq-frontend

# Rebuild with correct variables
docker-compose build --no-cache frontend
docker-compose up -d frontend
```

### Can't connect to backend from frontend

Make sure `VITE_API_URL` points to the correct backend URL. For docker-compose, services can communicate via service names:

```bash
# In docker-compose, frontend can access backend at:
VITE_API_URL=http://backend:8001
```

For external access (browser), use:
```bash
VITE_API_URL=http://localhost:8001
# or your domain
VITE_API_URL=https://api.yourdomain.com
```

## Maintenance

### Update containers

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose up -d --build
```

### View logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Clean up

```bash
# Stop and remove containers
docker-compose down

# Remove volumes (WARNING: deletes data)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```

## Security Recommendations

1. **Change default SECRET_KEY** in production
2. **Use HTTPS** with SSL certificates (nginx/traefik)
3. **Restrict CORS** origins in backend
4. **Use Docker secrets** for sensitive data
5. **Enable firewall** rules
6. **Regular updates** of base images and dependencies
7. **Scan images** for vulnerabilities: `docker scan soldieriq-backend`

## Architecture

```
┌─────────────────┐
│   nginx:alpine  │  ← Frontend (Port 80)
│   React/Vite    │
└────────┬────────┘
         │
         │ HTTP
         │
┌────────▼────────┐
│  python:3.11    │  ← Backend (Port 8001)
│   FastAPI/uv    │
└────────┬────────┘
         │
         ├─→ MongoDB (External)
         ├─→ Pinecone (External)
         ├─→ OpenAI/OpenRouter (External)
         └─→ iDrive E2 (External)
```

## Support

For issues or questions:
- Check logs: `docker-compose logs -f`
- Verify environment variables: `docker-compose config`
- Review health status: `docker-compose ps`
