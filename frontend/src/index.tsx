import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { KeycloakProvider } from './auth/KeycloakProvider';

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <React.StrictMode>
    <KeycloakProvider>
      <App />
    </KeycloakProvider>
  </React.StrictMode>
);
