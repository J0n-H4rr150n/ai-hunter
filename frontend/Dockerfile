FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY frontend/package*.json ./

# Install dependencies
RUN npm install

# Copy frontend files
COPY frontend/ .

# Build Tailwind CSS
RUN npm run build:css

# Expose port
EXPOSE 3000

# Start server
CMD ["npm", "start"]
