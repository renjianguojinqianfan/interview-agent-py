import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { ProviderItem } from '../types/llmProvider'
import { server } from '../test/server'
import SettingsPage from './SettingsPage'

const PROVIDER: ProviderItem = {
  id: 'dashscope',
  baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  maskedApiKey: 'sk-****',
  model: 'qwen-plus',
  embeddingModel: 'text-embedding-v3',
  embeddingDimensions: 1024,
  supportsEmbedding: true,
  temperature: 0.2,
  defaultChatProvider: true,
  defaultEmbeddingProvider: true,
}

/** 挂载时 loadData 并行拉取的 4 个配置端点；缺任一个都会因 onUnhandledRequest:'error' 使测试失败。 */
function mockMountEndpoints(): void {
  const ok = (data: unknown) => HttpResponse.json({ code: 200, message: 'ok', data })
  server.use(
    http.get('/api/llm-provider/list', () => ok([PROVIDER])),
    http.get('/api/llm-provider/default-provider', () =>
      ok({ defaultProvider: 'dashscope', defaultEmbeddingProvider: 'dashscope' }),
    ),
    http.get('/api/llm-provider/voice/asr', () =>
      ok({
        url: '',
        model: '',
        maskedApiKey: '',
        language: 'zh',
        format: 'pcm',
        sampleRate: 16000,
        enableTurnDetection: false,
        turnDetectionType: 'server_vad',
        turnDetectionThreshold: 0.5,
        turnDetectionSilenceDurationMs: 800,
      }),
    ),
    http.get('/api/llm-provider/voice/tts', () =>
      ok({
        model: '',
        maskedApiKey: '',
        voice: '',
        format: 'pcm',
        sampleRate: 24000,
        mode: 'default',
        languageType: 'Chinese',
        speechRate: 1,
        volume: 50,
      }),
    ),
  )
}

describe('SettingsPage 加载渲染', () => {
  it('挂载并行拉取配置端点 -> 渲染出供应商 id 与聊天模型', async () => {
    mockMountEndpoints()
    render(<SettingsPage />)

    // 稳定标题即时可见
    expect(screen.getByText('系统设置')).toBeInTheDocument()
    // list() 返回的字段经渲染上屏（若 4 端点契约任一断裂，render 会停在 loading，断言超时）
    expect(await screen.findByText('dashscope')).toBeInTheDocument()
    expect(await screen.findByText('qwen-plus')).toBeInTheDocument()
  })
})
