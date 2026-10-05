import { toUserMessage } from '@/api/errors';
import { Button, Modal, Space, Tag } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  classifyDatasource,
  deleteDataSource,
  disableDataSource,
  enableDataSource,
  listDatasources,
  scanDatasource,
} from '@/api/datasources';
import { qk } from '@/api/keys';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import ConfirmDanger from '@/components/ConfirmDanger';
import DataSourceCreateModal, { DS_TYPES } from './DataSourceCreateModal';
import EmptyState from '@/components/EmptyState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import PageHeader from '@/components/PageHeader';
import ScanModal from '@/components/ScanModal';
import TaskProgressLink from '@/components/TaskProgressLink';
import type { DataSource } from '@/types';
import { App } from 'antd';

/** 数据源列表（FE-01 §3.1）。keyset 游标分页。 */
export default function DataSourceListPage() {
  const { message } = App.useApp();
  const [filters, setFilters] = useState<FilterValues>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [scanTarget, setScanTarget] = useState<DataSource | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const qc = useQueryClient();

  const params = useMemo(
    () => ({
      keyword: filters.keyword as string | undefined,
      dsType: filters.dsType as string | undefined,
      enabled: filters.enabled as boolean | undefined,
    }),
    [filters],
  );
  const filterKey = JSON.stringify(params);
  const hasFilters = Boolean(
    filters.keyword || filters.dsType || filters.enabled !== undefined,
  );

  const invalidate = () => qc.invalidateQueries({ queryKey: qk.datasources.all });

  const columns: ColumnsType<DataSource> = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 70,
      render: (id: number) => <Link to={`/app/datasources/${id}`}>{id}</Link>,
    },
    { title: '编码', dataIndex: 'code', width: 160 },
    { title: '名称', dataIndex: 'name', width: 200 },
    { title: '类型', dataIndex: 'dsType', width: 120 },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 90,
      render: (v?: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '操作',
      width: 340,
      render: (_v, r) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => setScanTarget(r)}
          >
            扫描
          </Button>
          <Button
            type="link"
            size="small"
            onClick={async () => {
              try {
                const res = await classifyDatasource(r.id);
                const runId = res?.id ?? res?.runId;
                if (runId) {
                  Modal.success({
                    title: '分级已提交',
                    content: <TaskProgressLink id={runId} label={`查看任务 #${runId}`} />,
                  });
                }
                invalidate();
              } catch (e: any) {
                message.error(toUserMessage(e, '分级提交失败'));
              }
            }}
          >
            分级
          </Button>
          {r.enabled ? (
            <ConfirmDanger
              title="停用数据源"
              description={`停用后将不再对其执行扫描等操作：${r.code}`}
              okText="停用"
              onConfirm={async () => {
                try {
                  await disableDataSource(r.id);
                  message.success('已停用');
                  invalidate();
                } catch (e: any) {
                  message.error(toUserMessage(e, '操作失败'));
                }
              }}
            >
              <Button type="link" size="small" danger>
                停用
              </Button>
            </ConfirmDanger>
          ) : (
            <Button
              type="link"
              size="small"
              onClick={async () => {
                try {
                  await enableDataSource(r.id);
                  message.success('已启用');
                  invalidate();
                } catch (e: any) {
                  message.error(toUserMessage(e, '操作失败'));
                }
              }}
            >
              启用
            </Button>
          )}
          <ConfirmDanger
            title="删除数据源"
            description={`删除 ${r.code}${r.name ? `（${r.name}）` : ''} 后，其扫描任务与资产引用将不再可追溯，且无法从界面恢复。`}
            okText="删除"
            onConfirm={async () => {
              try {
                await deleteDataSource(r.id);
                message.success('已删除');
                invalidate();
              } catch (e: any) {
                message.error(toUserMessage(e, '删除失败'));
              }
            }}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </ConfirmDanger>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="数据源"
        subtitle="注册、连通性测试、启停、凭据轮换与扫描触发"
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            新建数据源
          </Button>
        }
      />
      <FilterBar
        fields={[
          { name: 'keyword', label: '关键字', type: 'text' },
          { name: 'dsType', label: '类型', type: 'select', options: DS_TYPES.map((t) => ({ label: t, value: t })) },
          {
            name: 'enabled',
            label: '状态',
            type: 'select',
            options: [
              { label: '启用', value: true },
              { label: '停用', value: false },
            ],
          },
        ]}
        values={filters}
        onChange={setFilters}
      />
      <DataTable<DataSource>
        columns={columns}
        queryKey={qk.datasources.list(params)}
        filterKey={filterKey}
        rowKey="id"
        scrollX={1000}
        empty={
          hasFilters ? (
            <EmptyState
              description="没有匹配的数据源"
              extra={<Button onClick={() => setFilters({})}>清除筛选</Button>}
            />
          ) : (
            <EmptyState
              description="暂无数据源"
              extra={
                <Button type="primary" onClick={() => setCreateOpen(true)}>
                  新建数据源
                </Button>
              }
            />
          )
        }
        fetcher={async (cursor) => listDatasources({ ...params, cursor })}
      />
      <DataSourceCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={invalidate}
      />
      <ScanModal
        open={scanTarget !== null}
        title={`扫描 ${scanTarget?.code ?? ''}`}
        confirmLoading={scanLoading}
        onCancel={() => setScanTarget(null)}
        onConfirm={async (allowWrite, database) => {
          if (!scanTarget) return;
          setScanLoading(true);
          try {
            const res = await scanDatasource(scanTarget.id, { allowWrite, database });
            const runId = res?.id ?? res?.runId ?? res?.scanRunId;
            if (runId) {
              Modal.success({
                title: '扫描已提交',
                content: <TaskProgressLink id={runId} label={`查看任务 #${runId}`} />,
              });
            } else {
              message.success('扫描完成');
            }
            invalidate();
          } catch (e: any) {
            message.error(toUserMessage(e, '扫描失败'));
          } finally {
            setScanLoading(false);
            setScanTarget(null);
          }
        }}
      />
    </div>
  );
}
