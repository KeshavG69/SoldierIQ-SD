# SoldierIQ Frontend - Docker Deployment

## Building the Docker Image

### Build with default values
```bash
docker build -t soldieriq-frontend .
```

### Build with environment variables
```bash
docker build \
  --build-arg NEXT_PUBLIC_API_URL=http://your-backend-api:8001 \
  --build-arg IDRIVEE2_REGION=us-east-1 \
  --build-arg IDRIVEE2_ENDPOINT_URL=https://s3.us-west-1.idrivee2.com \
  --build-arg IDRIVEE2_ACCESS_KEY_ID=your_access_key \
  --build-arg IDRIVEE2_SECRET_ACCESS_KEY=your_secret_key \
  --build-arg IDRIVEE2_BUCKET_NAME=soldieriq-documents \
  -t soldieriq-frontend .
```

## Running the Container

### Run with default configuration
```bash
docker run -p 3000:3000 soldieriq-frontend
```

### Run with environment variables (override build-time values)
```bash
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=http://your-backend-api:8001 \
  -e IDRIVEE2_REGION=us-east-1 \
  -e IDRIVEE2_ENDPOINT_URL=https://s3.us-west-1.idrivee2.com \
  -e IDRIVEE2_ACCESS_KEY_ID=your_access_key \
  -e IDRIVEE2_SECRET_ACCESS_KEY=your_secret_key \
  -e IDRIVEE2_BUCKET_NAME=soldieriq-documents \
  soldieriq-frontend
```

### Run with env file
```bash
# Create a .env file with your variables
docker run -p 3000:3000 --env-file .env.local soldieriq-frontend
```

## Environment Variables

### Required Variables

#### NEXT_PUBLIC_API_URL
- **Description**: Backend API URL (exposed to browser)
- **Default**: `http://localhost:8001`
- **Example**: `http://backend:8001` or `https://api.soldieriq.com`

#### IDRIVEE2_ENDPOINT_URL
- **Description**: iDriveE2 S3-compatible endpoint URL
- **Required**: Yes
- **Example**: `https://s3.us-west-1.idrivee2.com`

#### IDRIVEE2_ACCESS_KEY_ID
- **Description**: iDriveE2 access key ID
- **Required**: Yes
- **Security**: Keep this secret, never commit to version control

#### IDRIVEE2_SECRET_ACCESS_KEY
- **Description**: iDriveE2 secret access key
- **Required**: Yes
- **Security**: Keep this secret, never commit to version control

### Optional Variables

#### IDRIVEE2_REGION
- **Description**: AWS region format for iDriveE2
- **Default**: `us-east-1`

#### IDRIVEE2_BUCKET_NAME
- **Description**: S3 bucket name for document storage
- **Default**: `soldieriq-documents`

## Production Deployment

### Using Docker Compose (if needed later)
The project includes a `docker-compose.yml` for reference, but you can deploy without it by passing environment variables directly to the Docker run command.

### Health Check
The container includes a health check endpoint that runs every 30 seconds:
```bash
# Check container health
docker ps

# Manual health check
curl http://localhost:3000/api/health
```

### Security Notes
1. Never commit `.env.local` or files containing secrets
2. Use environment-specific configuration for production
3. Consider using Docker secrets or a secrets manager for sensitive values
4. The container runs as a non-root user (nextjs:nodejs) for security

## Troubleshooting

### Container won't start
```bash
# Check logs
docker logs <container-id>

# Run with interactive shell
docker run -it --entrypoint sh soldieriq-frontend
```

### Build fails
```bash
# Clean build
docker build --no-cache -t soldieriq-frontend .

# Check build logs
docker build -t soldieriq-frontend . 2>&1 | tee build.log
```

### Environment variables not working
- Ensure variables are passed at build time with `--build-arg`
- Or pass at runtime with `-e` flags
- Verify variables in container: `docker exec <container-id> env`
