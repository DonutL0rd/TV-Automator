import React, { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

// Type definitions based on the FastAPI backend
export interface Team {
  name: string;
  abbreviation: string;
  score: number | null;
}

export interface Game {
  game_id: string;
  provider: string;
  away_team: Team;
  home_team: Team;
  start_time: string;
  display_time: string;
  display_matchup: string;
  display_score: string;
  status: string; // 'scheduled', 'pre_game', 'live', 'final', 'postponed'
  status_label: string;
  is_watchable: boolean;
  venue: string;
  extra: any;
}

export interface Status {
  now_playing_game_id: string | null;
  youtube_mode: boolean;
  authenticated: boolean;
  browser_running: boolean;
  heartbeat_active: boolean;
}

interface TvAutomatorContextType {
  games: Game[];
  status: Status;
  connected: boolean;
  playGame: (gameId: string, feed?: string) => Promise<void>;
  stopPlayback: () => Promise<void>;
  playYoutube: (url: string) => Promise<void>;
}

const defaultStatus: Status = {
  now_playing_game_id: null,
  youtube_mode: false,
  authenticated: false,
  browser_running: false,
  heartbeat_active: false,
};

const TvAutomatorContext = createContext<TvAutomatorContextType | null>(null);

export const TvAutomatorProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [games, setGames] = useState<Game[]>([]);
  const [status, setStatus] = useState<Status>(defaultStatus);
  const [connected, setConnected] = useState<boolean>(false);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/api/ws`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'status') {
            setStatus(data);
          } else if (data.type === 'games') {
            setGames(data.games);
          }
        } catch (e) {
          console.error('Failed to parse WS message', e);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.error('WebSocket Error', err);
        ws.close();
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, []);

  const playGame = async (gameId: string, feed: string = 'HOME') => {
    try {
      await fetch(`/api/play/${gameId}?feed=${feed}`, { method: 'POST' });
    } catch (e) {
      console.error('Play game error:', e);
    }
  };

  const stopPlayback = async () => {
    try {
      await fetch('/api/stop', { method: 'POST' });
    } catch (e) {
      console.error('Stop playback error:', e);
    }
  };

  const playYoutube = async (url: string) => {
    try {
      await fetch('/api/youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
    } catch (e) {
      console.error('YouTube play error:', e);
    }
  };

  return (
    <TvAutomatorContext.Provider value={{ games, status, connected, playGame, stopPlayback, playYoutube }}>
      {children}
    </TvAutomatorContext.Provider>
  );
};

export const useTvAutomator = () => {
  const ctx = useContext(TvAutomatorContext);
  if (!ctx) {
    throw new Error('useTvAutomator must be used within a TvAutomatorProvider');
  }
  return ctx;
};
