import React from 'react';
import './LoadingScreen.css';

const LoadingScreen = () => {
  return (
    <div className="loading-screen">
      <div className="logo-container">
        <div className="logo-wrapper">
          <svg className="logo-svg" viewBox="0 0 1000 300" xmlns="http://www.w3.org/2000/svg">
            <text x="50%" y="50%" dominantBaseline="middle" textAnchor="middle" className="logo-text">
              PE STUDIO
            </text>
          </svg>
          <div className="glow-effect"></div>
        </div>
        <div className="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
  );
};

export default LoadingScreen;
