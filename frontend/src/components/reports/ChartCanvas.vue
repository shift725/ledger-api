<script setup lang="ts">
import { onMounted, onBeforeUnmount, shallowRef, watch } from 'vue'
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  DoughnutController,
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
} from 'chart.js'
import type { ChartType, ChartData, ChartOptions } from 'chart.js'

// 手動註冊（樹搖）：只註冊四張報表用到的 controller/element。不註冊 Filler
// （初版不做面積填色），永不用 chart.js/auto。
Chart.register(
  LineController,
  LineElement,
  PointElement,
  DoughnutController,
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
)

const props = defineProps<{
  type: ChartType
  data: ChartData
  options?: ChartOptions
}>()

const canvas = shallowRef<HTMLCanvasElement | null>(null)
let chart: Chart | null = null

onMounted(() => {
  if (!canvas.value) return
  chart = new Chart(canvas.value, { type: props.type, data: props.data, options: props.options })
})

// 資料/選項變更就地重建（報表 dataset 很小，整批 update 即可，不做逐點 diff）。
watch(
  () => [props.data, props.options],
  () => {
    if (!chart) return
    chart.data = props.data
    if (props.options) chart.options = props.options
    chart.update()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  chart?.destroy()
  chart = null
})
</script>

<template>
  <canvas ref="canvas"></canvas>
</template>
