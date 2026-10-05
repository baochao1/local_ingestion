import { useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useDatasourceMap } from '@/hooks/useDatasourceName';
import { qk } from '@/api/keys';
import {
  ackRisk,
  exportReport,
  listAccounts,
  listChanges,
  listRisks,
  triggerPermissionScan,
  type PermissionAccount,
  type PermissionChange,
  type PermissionRisk,
  type RiskSeverity,
  type RiskType,
} from '@/api/permissions';
import { toUserMessage } from '@/api/errors';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';

const RISK_LABEL: Record<RiskType, string> = {
  super: '超级账号',
  locked: '已锁定',
  dormant: '僵尸/久未登录',
  orphan: '无主账号',
  excessive: '过度授权',
  high_sensitivity: '高敏访问',
};

const SEVERITY_COLOR: Record<RiskSeverity, string> = {
  high: 'red',
  medium: 'orange',
  info: 'blue',
  low: 'default',
};

export default function PermissionsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const { data: dsMap, isLoading: dsLoading } = useDatasourceMap();
  const [dsId, setDsId] = useState<number | undefined>(undefined);

  // 默认选中第一个可用数据源
  useEffect(() => {
    if (dsId != null || !dsMap || dsMap.size === 0) return;
    const first = dsMap.keys().next().value as number | undefined;
    if (first != null) setDsId(first);
  }, [dsMap, dsId]);

  const dsOptions = useMemo(
    () => Array.from(dsMap?.entries() ?? []).map(([id, name]) => ({ value: id, label: name })),
    [dsMap],
  );

  const ready = dsId != null;

  const accountsQ = useQuery({
    queryKey: qk.permissions.accounts(dsId ?? 0),
    queryFn: () => listAccounts(dsId as number),
    enabled: ready,
  });
  const risksQ = useQuery({
    queryKey: qk.permissions.risks(dsId ?? 0),
    queryFn: () => listRisks(dsId as number),
    enabled: ready,
  });
  const changesQ = useQuery({
    queryKey: qk.permissions.changes(dsId ?? 0),
    queryFn: () => listChanges(dsId as number),
    enabled: ready,
  });
  const exportQ = useQuery({
    queryKey: qk.permissions.export(dsId ?? 0),
    queryFn: () => exportReport(dsId as number),
    enabled: ready,
  });

  const onAck = async (riskId: string) => {
    if (dsId == null) return;
    try {
      await ackRisk(dsId, riskId);
      message.success('已确认风险');
      await qc.invalidateQueries({ queryKey: ['permissions'] });
    } catch (e: unknown) {
      message.error(toUserMessage(e, '确认失败'));
    }
  };

  const onTrigger = async () => {
    if (dsId == null) return;
    try {
      const run = await triggerPermissionScan(dsId);
      message.success(`已提交权限采集任务 #${run.task_id}`);
    } catch (e: unknown) {
      message.error(toUserMessage(e, '提交失败'));
    }
  };

  const onDownload = async () => {
    if (dsId == null) return;
    try {
      const rep = await exportReport(dsId);
      const blob = new Blob([JSON.stringify(rep, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `permission-report-ds${dsId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      message.error(toUserMessage(e, '导出失败'));
    }
  };

  const accountColumns: ColumnsType<PermissionAccount> = [
    { title: '账号', dataIndex: 'account', render: (v: string) => <span className="mono">{v}</span> },
    { title: '类型', dataIndex: 'type', render: (v: string | null) => v ?? '-' },
    {
      title: '超级',
      dataIndex: 'is_super',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="red">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '锁定',
      dataIndex: 'is_locked',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="gold">是</Tag> : <Tag>否</Tag>),
    },
    { title: 'Host', dataIndex: 'host', render: (v: string | null) => v ?? '-' },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      render: (v: string | null) => (v ? String(v).replace('T', ' ').slice(0, 19) : '—'),
    },
  ];

  const riskColumns: ColumnsType<PermissionRisk> = [
    {
      title: '级别',
      dataIndex: 'severity',
      width: 90,
      render: (s: RiskSeverity) => <Tag color={SEVERITY_COLOR[s]}>{s}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 120,
      render: (t: RiskType) => RISK_LABEL[t] ?? t,
    },
    { title: '账号', dataIndex: 'account', render: (v: string) => <span className="mono">{v}</span> },
    { title: '对象', dataIndex: 'object_fqn', render: (v?: string) => (v ? <span className="mono">{v}</span> : '-') },
    { title: '权限', dataIndex: 'privilege', render: (v?: string) => v ?? '-' },
    { title: '说明', dataIndex: 'detail' },
    {
      title: '状态',
      dataIndex: 'acked',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="green">已确认</Tag> : <Tag>待处理</Tag>),
    },
    {
      title: '操作',
      width: 90,
      render: (_v, r) => (
        <Button type="link" size="small" disabled={r.acked} onClick={() => void onAck(r.id)}>
          确认
        </Button>
      ),
    },
  ];

  const changeColumns: ColumnsType<PermissionChange> = [
    {
      title: '变更',
      dataIndex: 'kind',
      width: 90,
      render: (k: PermissionChange['kind']) =>
        k === 'added' ? <Tag color="green">新增</Tag> : <Tag color="red">撤销</Tag>,
    },
    { title: '账号ID', dataIndex: 'account_id', width: 90 },
    { title: '权限', dataIndex: 'privilege', width: 110 },
    { title: '对象', dataIndex: 'object_fqn', render: (v: string) => <span className="mono">{v}</span> },
  ];

  const tabAccounts = (
    <Card>
      {accountsQ.isLoading ? (
        <LoadingSkeleton rows={5} />
      ) : accountsQ.isError ? (
        <ErrorState error={accountsQ.error} onRetry={() => void accountsQ.refetch()} />
      ) : (accountsQ.data ?? []).length === 0 ? (
        <Empty description="该数据源暂无账号（请先触发权限采集）" />
      ) : (
        <Table<PermissionAccount>
          columns={accountColumns}
          dataSource={accountsQ.data ?? []}
          rowKey="account"
          size="small"
          pagination={{ pageSize: 20 }}
        />
      )}
    </Card>
  );

  const tabRisks = (
    <Card>
      {risksQ.isLoading ? (
        <LoadingSkeleton rows={5} />
      ) : risksQ.isError ? (
        <ErrorState error={risksQ.error} onRetry={() => void risksQ.refetch()} />
      ) : (risksQ.data ?? []).length === 0 ? (
        <Empty description="未检出权限风险" />
      ) : (
        <Table<PermissionRisk>
          columns={riskColumns}
          dataSource={risksQ.data ?? []}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 20 }}
        />
      )}
    </Card>
  );

  const tabChanges = (
    <Card>
      {changesQ.isLoading ? (
        <LoadingSkeleton rows={5} />
      ) : changesQ.isError ? (
        <ErrorState error={changesQ.error} onRetry={() => void changesQ.refetch()} />
      ) : (changesQ.data ?? []).length === 0 ? (
        <Empty description="暂无基线对比（请先在「导出」页刷新基线）" />
      ) : (
        <Table<PermissionChange>
          columns={changeColumns}
          dataSource={changesQ.data ?? []}
          rowKey={(r) => `${r.kind}-${r.account_id}-${r.object_fqn}-${r.privilege}`}
          size="small"
          pagination={{ pageSize: 20 }}
        />
      )}
    </Card>
  );

  const tabExport = (
    <Card>
      <Space style={{ marginBottom: 16 }}>
        <Button onClick={() => void exportQ.refetch()} loading={exportQ.isFetching}>
          刷新
        </Button>
        <Button type="primary" onClick={() => void onDownload()}>
          下载权限报告 (JSON)
        </Button>
      </Space>
      {exportQ.isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : exportQ.isError ? (
        <ErrorState error={exportQ.error} onRetry={() => void exportQ.refetch()} />
      ) : exportQ.data ? (
        <Descriptions bordered column={2} size="small">
          <Descriptions.Item label="数据源ID">{exportQ.data.datasource_id}</Descriptions.Item>
          <Descriptions.Item label="账号数">{exportQ.data.accounts}</Descriptions.Item>
          <Descriptions.Item label="风险项">{exportQ.data.risks}</Descriptions.Item>
          <Descriptions.Item label="高敏风险">
            {exportQ.data.high_sensitivity_count}
          </Descriptions.Item>
          <Descriptions.Item label="生成时间" span={2}>
            {String(exportQ.data.generated_at).replace('T', ' ').slice(0, 19)}
          </Descriptions.Item>
        </Descriptions>
      ) : null}
    </Card>
  );

  return (
    <div>
      <PageHeader
        title="权限分析"
        subtitle="账号 / 授权 / 风险 / 变更 —— MOD-08"
        extra={
          <Space>
            <Select
              style={{ minWidth: 200 }}
              placeholder={dsLoading ? '加载数据源…' : '选择数据源'}
              loading={dsLoading}
              value={dsId}
              options={dsOptions}
              onChange={(v) => setDsId(v as number)}
              showSearch
              optionFilterProp="label"
            />
            <Button onClick={() => void onTrigger()} disabled={!ready}>
              触发权限采集
            </Button>
          </Space>
        }
      />
      {!ready ? (
        <Empty description="请先选择数据源" />
      ) : (
        <Tabs
          items={[
            { key: 'accounts', label: '账号清单', children: tabAccounts },
            { key: 'risks', label: '风险项', children: tabRisks },
            { key: 'changes', label: '权限变更', children: tabChanges },
            { key: 'export', label: '导出报告', children: tabExport },
          ]}
        />
      )}
    </div>
  );
}
