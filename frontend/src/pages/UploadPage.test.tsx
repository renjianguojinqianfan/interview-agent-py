import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { server } from '../test/server'
import UploadPage from './UploadPage'

/** FileUploadCard 的文件选择走隐藏 input（无可访问名），按 id 取。 */
function fileInput(): HTMLInputElement {
  const input = document.getElementById('file-upload-input')
  if (!(input instanceof HTMLInputElement)) {
    throw new Error('未找到文件上传 input')
  }
  return input
}

/** 与 input accept=".pdf,.doc,.docx,.txt" 匹配的文件（userEvent.upload 会按 accept 过滤）。 */
function resumeFile(): File {
  return new File(['我的简历：三年 Java 经验'], 'resume.txt', { type: 'text/plain' })
}

describe('UploadPage 简历上传交互', () => {
  it('选文件并点“开始上传” -> POST /api/resumes/upload -> 回调 resumeId', async () => {
    let uploadCalled = false
    server.use(
      http.post('/api/resumes/upload', () => {
        uploadCalled = true
        return HttpResponse.json({
          code: 200,
          message: 'ok',
          data: { storage: { fileKey: 'k', fileUrl: 'u', resumeId: 42 }, duplicate: false },
        })
      }),
    )
    const onUploadComplete = vi.fn()
    render(<UploadPage onUploadComplete={onUploadComplete} />)

    await userEvent.upload(fileInput(), resumeFile())
    await userEvent.click(await screen.findByRole('button', { name: '开始上传' }))

    // 点按钮 -> 命中上传端点 -> 拿到 resumeId 后回调（按钮 -> 请求 -> 数据 -> 状态）
    await waitFor(() => expect(onUploadComplete).toHaveBeenCalledWith(42))
    expect(uploadCalled).toBe(true)
  })

  it('后端返回错误码 -> 渲染错误信息且不回调', async () => {
    server.use(
      // 后端统一 HTTP 200 + Result（ADR-0003）：失败经 code!=200 表达
      http.post('/api/resumes/upload', () =>
        HttpResponse.json({ code: 400, message: '不支持的文件类型', data: null }),
      ),
    )
    const onUploadComplete = vi.fn()
    render(<UploadPage onUploadComplete={onUploadComplete} />)

    await userEvent.upload(fileInput(), resumeFile())
    await userEvent.click(await screen.findByRole('button', { name: '开始上传' }))

    // 渲染对结果：错误信息上屏，且不触发成功回调
    expect(await screen.findByText('不支持的文件类型')).toBeInTheDocument()
    expect(onUploadComplete).not.toHaveBeenCalled()
  })
})
