import React, { useState } from 'react';
import { useTvAutomator } from '../hooks/useTvAutomator';
import { Play, Video as YoutubeIcon } from 'lucide-react';
import './YouTube.css';

const YouTube: React.FC = () => {
  const { playYoutube } = useTvAutomator();
  const [url, setUrl] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url) {
      playYoutube(url);
      setUrl('');
    }
  };

  return (
    <div className="view-container animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">YouTube</h1>
          <p className="page-subtitle">Cast videos to the TV</p>
        </div>
      </div>

      <div className="youtube-panel glass-panel">
        <div className="panel-icon">
          <YoutubeIcon size={32} color="var(--neon-red)" />
        </div>
        
        <form className="youtube-form" onSubmit={handleSubmit}>
          <input 
            type="text" 
            className="modern-input" 
            placeholder="Paste YouTube URL here..." 
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button type="submit" className="btn btn-primary btn-yt" disabled={!url}>
            <Play size={16} /> Cast to TV
          </button>
        </form>
      </div>
    </div>
  );
};

export default YouTube;
