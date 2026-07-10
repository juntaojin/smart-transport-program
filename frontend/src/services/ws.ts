export class DashboardWebSocket {
  private url: string;
  private ws: WebSocket | null = null;
  private reconnectTimer: any = null;
  private onMessageCallback: (data: any) => void;
  private onImageCallback: (blob: Blob) => void;
  private onStatusCallback: (status: 'connecting' | 'connected' | 'disconnected') => void;
  private active = false;

  constructor(
    onMessage: (data: any) => void,
    onImage: (blob: Blob) => void,
    onStatus: (status: 'connecting' | 'connected' | 'disconnected') => void
  ) {
    this.onMessageCallback = onMessage;
    this.onImageCallback = onImage;
    this.onStatusCallback = onStatus;
    
    const envUrl = import.meta.env.VITE_WS_URL;
    if (envUrl) {
      this.url = envUrl;
    } else {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      this.url = `${proto}//${window.location.host}/ws/dashboard`;
    }
  }

  public connect() {
    this.active = true;
    this.disconnect();
    this.onStatusCallback('connecting');

    try {
      this.ws = new WebSocket(this.url);
      this.ws.binaryType = 'blob';
      
      this.ws.onopen = () => {
        this.onStatusCallback('connected');
        console.log('Dashboard WebSocket connected');
      };

      this.ws.onmessage = (event) => {
        if (event.data instanceof Blob) {
          this.onImageCallback(event.data);
          return;
        }
        try {
          const data = JSON.parse(event.data as string);
          this.onMessageCallback(data);
        } catch (err) {
          console.error('Error parsing WS message:', err);
        }
      };

      this.ws.onclose = () => {
        this.onStatusCallback('disconnected');
        this.scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        console.error('WS Error:', err);
        this.onStatusCallback('disconnected');
        this.disconnect();
      };
    } catch (err) {
      console.error('Failed to establish WS connection:', err);
      this.onStatusCallback('disconnected');
      this.scheduleReconnect();
    }
  }

  public disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onopen = null;
      this.ws.onmessage = null;
      try {
        this.ws.close();
      } catch {}
      this.ws = null;
    }
  }

  public stop() {
    this.active = false;
    this.disconnect();
  }

  private scheduleReconnect() {
    if (!this.active) return;
    if (this.reconnectTimer) return;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      console.log('Attempting WS reconnect...');
      this.connect();
    }, 3000);
  }
}
