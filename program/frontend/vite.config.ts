import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const targetHost = env.VITE_DEV_SERVER_HOST || '127.0.0.1';
  const targetPort = env.VITE_DEV_SERVER_PORT || '8000';
  const target = `http://${targetHost}:${targetPort}`;

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: target,
          changeOrigin: true,
        },
      },
    },
  };
});
