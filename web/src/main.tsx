import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import 'antd/dist/reset.css';
import { antdTheme } from './theme';
import App from './App';
import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
);
