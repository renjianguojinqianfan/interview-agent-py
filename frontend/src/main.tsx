import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { setUnauthorizedHandler } from './api/request'
import './index.css'

// 401 时统一跳登录（HTTP 200 + Result.code=401 语义）
setUnauthorizedHandler(() => {
    window.location.assign('/login');
});

// 初始化深色模式（避免页面闪烁）
(function initTheme() {
    const stored = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = stored === 'dark' || (!stored && prefersDark);
    if (isDark) {
        document.documentElement.classList.add('dark');
    }
})();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
