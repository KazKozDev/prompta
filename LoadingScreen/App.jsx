import React, { useState, useEffect } from 'react';
import LoadingScreen from './LoadingScreen';
import './App.css';

function App() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(false);
    }, 3500);

    return () => clearTimeout(timer);
  }, []);

  return (
    <>
      {loading && <LoadingScreen />}
      <div className="app">
        <h1>Welcome to PE STUDIO</h1>
        {/* Your app content */}
      </div>
    </>
  );
}

export default App;
