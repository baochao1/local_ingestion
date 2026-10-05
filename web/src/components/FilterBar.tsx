import { Button, DatePicker, Input, InputNumber, Select, Typography } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';

export interface FilterField {
  name: string;
  label: string;
  type: 'text' | 'select' | 'dateRange' | 'number';
  options?: { label: string; value: unknown }[];
  placeholder?: string;
}

export type FilterValues = Record<string, unknown>;

export interface FilterBarProps {
  fields: FilterField[];
  values?: FilterValues;
  onChange: (values: FilterValues) => void;
  onReset?: () => void;
  onSearch?: (values: FilterValues) => void;
  loading?: boolean;
}

const DATE_FORMAT = 'YYYY-MM-DD';

/** 行内筛选条件组（FE-00 §5.2）。dateRange 值统一存 [开始, 结束] 字符串数组。 */
export function FilterBar({
  fields,
  values,
  onChange,
  onReset,
  onSearch,
  loading,
}: FilterBarProps) {
  const [draft, setDraft] = useState<FilterValues>(values ?? {});

  useEffect(() => {
    setDraft(values ?? {});
  }, [values]);

  const setField = (name: string, value: unknown) => {
    const next = { ...draft, [name]: value };
    setDraft(next);
    onChange(next);
  };

  const handleSearch = () => {
    onChange(draft);
    onSearch?.(draft);
  };

  const handleReset = () => {
    const cleared: FilterValues = {};
    fields.forEach((f) => {
      cleared[f.name] = undefined;
    });
    setDraft(cleared);
    onChange(cleared);
    onReset?.();
  };

  return (
    <div
      style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: 16 }}
    >
      {fields.map((field) => (
        <span key={field.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Typography.Text>{field.label}</Typography.Text>
          {field.type === 'text' ? (
            <Input
              aria-label={field.label}
              allowClear
              style={{ width: 200 }}
              placeholder={field.placeholder ?? `请输入${field.label}`}
              value={(draft[field.name] as string) ?? ''}
              onChange={(e) => setField(field.name, e.target.value || undefined)}
              onPressEnter={handleSearch}
            />
          ) : null}
          {field.type === 'select' ? (
            <Select
              aria-label={field.label}
              allowClear
              style={{ minWidth: 160 }}
              placeholder={field.placeholder ?? `请选择${field.label}`}
              options={(field.options ?? []).map((o) => ({
                label: o.label,
                value: o.value as string | number,
              }))}
              value={(draft[field.name] as string | number | undefined) ?? undefined}
              onChange={(v) => setField(field.name, v ?? undefined)}
            />
          ) : null}
          {field.type === 'number' ? (
            <InputNumber
              aria-label={field.label}
              style={{ width: 140 }}
              placeholder={field.placeholder ?? `请输入${field.label}`}
              value={(draft[field.name] as number | undefined) ?? undefined}
              onChange={(v) => setField(field.name, v ?? undefined)}
            />
          ) : null}
          {field.type === 'dateRange' ? (
            <DatePicker.RangePicker
              aria-label={`${field.label} 日期范围`}
              placeholder={[field.placeholder ?? '开始日期', '结束日期']}
              value={
                (() => {
                  const v = draft[field.name];
                  if (!Array.isArray(v) || v.length < 2 || !v[0] || !v[1]) return undefined as never;
                  return [dayjs(String(v[0])), dayjs(String(v[1]))] as never;
                })()
              }
              onChange={(dates) => {
                const next =
                  dates && dates[0] && dates[1]
                    ? [dates[0].format(DATE_FORMAT), dates[1].format(DATE_FORMAT)]
                    : undefined;
                setField(field.name, next);
              }}
            />
          ) : null}
        </span>
      ))}
      <span style={{ display: 'inline-flex', gap: 8 }}>
        <Button type="primary" loading={loading} onClick={handleSearch}>
          查询
        </Button>
        <Button onClick={handleReset}>重置</Button>
      </span>
    </div>
  );
}

export default FilterBar;
