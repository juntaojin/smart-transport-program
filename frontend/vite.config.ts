import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  
  // Try to parse server_ip and enable_ssl from config.yaml at the root directory
  let serverIp = '127.0.0.1';
  let enableSsl = false;
  try {
    const yamlPath = path.resolve(__dirname, '../config.yaml');
    if (fs.existsSync(yamlPath)) {
      const configYaml = fs.readFileSync(yamlPath, 'utf-8');
      
      const ipMatch = configYaml.match(/server_ip:\s*["']?([^"'\s]+)["']?/);
      if (ipMatch && ipMatch[1]) {
        serverIp = ipMatch[1];
      }
      
      const sslMatch = configYaml.match(/enable_ssl:\s*(true|false)/);
      if (sslMatch && sslMatch[1] === 'true') {
        enableSsl = true;
      }
    }
  } catch (e) {
    console.warn('Failed to parse config.yaml, using env/fallback.', e);
  }

  const targetHost = env.VITE_DEV_SERVER_HOST || serverIp;
  const targetPort = env.VITE_DEV_SERVER_PORT || '8000';
  
  const httpProto = enableSsl ? 'https' : 'http';
  const target = `${httpProto}://${targetHost}:${targetPort}`;
  
  // Use empty string to fallback to current location host, enabling proxying of WebSockets via Vite dev server
  const wsUrl = env.VITE_WS_URL || '';

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    define: {
      'import.meta.env.VITE_WS_URL': JSON.stringify(wsUrl),
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: target,
          changeOrigin: true,
          secure: false, // Bypass self-signed SSL certificate check
        },
        '/ws': {
          target: target,
          changeOrigin: true,
          secure: false, // Bypass self-signed SSL certificate check
          ws: true,      // Proxy WebSocket connections
        },
      },
    },
  };
});
