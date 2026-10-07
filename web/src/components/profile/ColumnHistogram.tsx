import { useRef, useEffect } from 'react';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ProfileHistogram } from '@/api/profiles';

// 按需注册而非 import 整个 echarts：只用到柱状图，全量包会多出约 1MB。
echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

export interface ColumnHistogramProps {
  histogram: ProfileHistogram;
  height?: number;
}

/** 列取值分布直方图（FR-M2.1 / FR-M2.2）。 */
export function ColumnHistogram({ histogram, height = 180 }: ColumnHistogramProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const chart = echarts.init(node);
    chart.setOption({
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: histogram.labels,
        axisLabel: { interval: 'auto', hideOverlap: true },
      },
      yAxis: { type: 'value', name: '行数' },
      series: [{ type: 'bar', data: histogram.counts, barMaxWidth: 32 }],
    });

    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
    };
  }, [histogram]);

  return <div ref={ref} style={{ width: '100%', height }} />;
}

export default ColumnHistogram;
