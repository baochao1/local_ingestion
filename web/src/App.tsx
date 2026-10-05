import { App as AntdApp } from 'antd';
import { BrowserRouter } from 'react-router-dom';
import AppRoutes from './router';

export default function App() {
  return (
    // antd `App` 提供 message/notification/modal 的上下文实例，
    // 供各页面通过 App.useApp() 获取（替代静态 message，避免主题/上下文告警）。
    <AntdApp>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AntdApp>
  );
}
