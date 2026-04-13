import React, { useState } from 'react';
import { useTvAutomator, type Game } from '../hooks/useTvAutomator';
import { Play, Tv, Calendar } from 'lucide-react';
import './Dashboard.css';

const GameCard: React.FC<{ game: Game; onPlay: (id: string, feed: string) => void; isPlaying: boolean }> = ({ game, onPlay, isPlaying }) => {
  const isLive = game.status === 'live';
  
  return (
    <div className={`game-card glass-panel ${isLive ? 'live live-glow' : ''} ${isPlaying ? 'playing' : ''}`}>
      <div className="card-header">
        <span className={`status-badge ${game.status}`}>
          {game.status_label}
        </span>
        <span className="game-time">{game.display_time}</span>
      </div>

      <div className="matchup-row">
        <div className="team-col">
          <div className="team-abbr tracking-wide">{game.away_team.abbreviation}</div>
          <div className="team-score">{game.away_team.score ?? '-'}</div>
        </div>
        
        <div className="separator">@</div>
        
        <div className="team-col right">
          <div className="team-abbr tracking-wide">{game.home_team.abbreviation}</div>
          <div className="team-score">{game.home_team.score ?? '-'}</div>
        </div>
      </div>

      <div className="card-foot">
        {game.is_watchable ? (
          <div className="play-actions">
            <button className="btn btn-neon flex-1" onClick={() => onPlay(game.game_id, 'HOME')}>
              <Play size={14} /> Home Feed
            </button>
            <button className="btn flex-1" onClick={() => onPlay(game.game_id, 'AWAY')}>
              Away Feed
            </button>
          </div>
        ) : (
          <div className="not-watchable">
            {game.status === 'final' ? 'Game Final - Condensed not ready' : 'Not Watchable Yet'}
          </div>
        )}
      </div>
    </div>
  );
};

const Dashboard: React.FC = () => {
  const { games, status, playGame } = useTvAutomator();
  const [dateStr, setDateStr] = useState<string>(''); // Default empty for today

  return (
    <div className="view-container animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Select a live game to display on screen</p>
        </div>
        
        <div className="date-nav">
          <button className="btn" onClick={() => setDateStr('2026-04-12')}><Calendar size={14}/> Previous</button>
          <span className="current-date">{dateStr || 'Today'}</span>
          <button className="btn" disabled>Next</button>
        </div>
      </div>

      <div className="game-grid">
        {games.length === 0 ? (
          <div className="empty-state">
            <Tv size={48} />
            <p>No games found</p>
          </div>
        ) : (
          games.map((g) => (
            <GameCard 
              key={g.game_id} 
              game={g} 
              onPlay={playGame} 
              isPlaying={status.now_playing_game_id === g.game_id} 
            />
          ))
        )}
      </div>
    </div>
  );
};

export default Dashboard;
