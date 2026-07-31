import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { resumeApi } from '../api/resume'
import UploadPage from './UploadPage'

// 模块级 mock：绕过 jsdom FormData/axios 跨平台差异（CI Linux 环境 FormData + MSW 交互不稳定），
// 测试焦点为组件行为（点按钮 → 调 API → 渲染结果），真实网络层由后端 integration 竖切守护。
vi.mock('../api/resume', () => ({
  resumeApi: { uploadAndAnalyze: vi.fn() },
}))

/** FileUploadCard 的文件选择走隐藏 input（无可访问名），按 id 取。 */
function fileInput(): HTMLInputElement {
  const input = document.getElementById('file-upload-input')
  if (!(input instanceof HTMLInputElement)) {
    throw new Error('未找到文件上传 input')
  }
  return input
}

/** 与 input accept=".pdf,.doc,.docx,.txt" 匹配的文件（userEvent.upload 按 accept 过滤）。 */
function resumeFile(): File {
  return new File(['我的简历：三年 Java 经验'], 'resume.txt', { type: 'text/plain' })
}

describe('UploadPage 简历上传交互', () => {
  it('选文件并点"开始上传" -> 调用 uploadAndAnalyze -> 回调 resumeId', async () => {
    vi.mocked(resumeApi.uploadAndAnalyze).mockResolvedValue({
      storage: { fileKey: 'k', fileUrl: 'u', resumeId: 42 },
      duplicate: false,
    })
    const onUploadComplete = vi.fn()
    render(<UploadPage onUploadComplete={onUploadComplete} />)

    const input = fileInput()
    const file = resumeFile()
    Object.defineProperty(input, 'files', { value: [file], writable: false })
    fireEvent.change(input)
    await userEvent.click(await screen.findByRole('button', { name: '开始上传' }))

    // 点按钮 -> 调对 API（传 File）-> 拿到 resumeId 后回调（按钮 -> 数据 -> 状态）
    await waitFor(() => expect(onUploadComplete).toHaveBeenCalledWith(42))
    expect(resumeApi.uploadAndAnalyze).toHaveBeenCalledWith(expect.any(File))
  })

  it('API 抛错 -> 渲染错误信息且不回调', async () => {
    vi.mocked(resumeApi.uploadAndAnalyze).mockRejectedValue(new Error('不支持的文件类型'))
    const onUploadComplete = vi.fn()
    render(<UploadPage onUploadComplete={onUploadComplete} />)

    const input = fileInput()
    const file = resumeFile()
    Object.defineProperty(input, 'files', { value: [file], writable: false })
    fireEvent.change(input)
    await userEvent.click(await screen.findByRole('button', { name: '开始上传' }))

    // 渲染对结果：错误信息上屏，且不触发成功回调
    expect(await screen.findByText('不支持的文件类型')).toBeInTheDocument()
    expect(onUploadComplete).not.toHaveBeenCalled()
  })
})
