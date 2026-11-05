import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
// Imported for its side effect: it puts the stored theme on the document before the first paint, so
// a saved light choice does not flash dark on the way in.
import './components/theme.js'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)