import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { KnowledgeBaseDocumentItem, KnowledgeBaseItem, KnowledgeBaseStats } from '../api/knowledgebase'
import { server } from '../test/server'
import KnowledgeBaseManagePage from './KnowledgeBaseManagePage'

const MOCK_KB: KnowledgeBaseItem = {
  id: 1,
  name: '测试知识库',
  originalFilename: 'test.pdf',
  fileSize: 1024,
  contentType: 'application/pdf',
  vectorStatus: 'COMPLETED',
  vectorError: null,
  chunkCount: 5,
  uploadedAt: '2026-01-01T00:00:00Z',
  lastAccessedAt: '2026-01-01T00:00:00Z',
  category: null,
  questionCount: 0,
  accessCount: 0,
  questionGenStatus: 'NONE',
  questionGenError: null,
}

const MOCK_DOC: KnowledgeBaseDocumentItem = {
  id: 10,
  knowledgeBaseId: 1,
  originalFilename: 'doc.pdf',
  fileSize: 512,
  contentType: 'application/pdf',
  vectorStatus: 'COMPLETED',
  vectorError: null,
  chunkCount: 2,
  uploadedAt: '2026-01-01T00:00:00Z',
}

const MOCK_STATS: KnowledgeBaseStats = {
  totalCount: 1,
  totalQuestionCount: 0,
  totalAccessCount: 0,
  completedCount: 1,
  processingCount: 0,
}

/** 挂载时页面并行拉取的 3 个端点 */
function mockMountEndpoints(): void {
  const ok = (data: unknown) => HttpResponse.json({ code: 200, message: 'ok', data })
  server.use(
    http.get('/api/knowledgebase/stats', () => ok(MOCK_STATS)),
    http.get('/api/knowledgebase/list', () => ok([MOCK_KB])),
    http.get('/api/knowledgebase/categories', () => ok([])),
  )
}

/** 展开文档面板并加载文档列表 */
function mockWithDocuments(): void {
  mockMountEndpoints()
  server.use(
    http.get('/api/knowledgebase/1/documents', () =>
      HttpResponse.json({ code: 200, message: 'ok', data: [MOCK_DOC] }),
    ),
  )
}

/** 等待多轮微任务刷新（确保异步 API → setState → re-render 链路完成） */
function flush(ms = 100): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

describe('KnowledgeBaseManagePage', () => {
  let alertSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
  })

  afterEach(() => {
    alertSpy.mockRestore()
  })

  describe('文档删除二次确认 (Issue #69)', () => {
    it('点击文档删除按钮后弹出确认对话框，取消则不发送删除请求', async () => {
      mockWithDocuments()
      const user = userEvent.setup()

      render(<KnowledgeBaseManagePage onUpload={() => {}} onChat={() => {}} />)

      expect(await screen.findByText('测试知识库')).toBeInTheDocument()

      const expandBtn = screen.getByTitle('文档列表')
      await user.click(expandBtn)

      expect(await screen.findByText('doc.pdf')).toBeInTheDocument()

      const deleteBtn = screen.getByTitle('删除文档')
      await user.click(deleteBtn)

      expect(await screen.findByText('确定删除')).toBeInTheDocument()

      const cancelBtn = screen.getByText('取消')
      await user.click(cancelBtn)

      await waitFor(() => {
        expect(screen.queryByText('确定删除')).not.toBeInTheDocument()
      })
    })

    it('确认删除后才发送删除请求', async () => {
      mockMountEndpoints()

      let deleteCalled = false
      let documentsReturn = [MOCK_DOC]
      server.use(
        http.get('/api/knowledgebase/1/documents', () =>
          HttpResponse.json({ code: 200, message: 'ok', data: documentsReturn }),
        ),
        http.delete('/api/knowledgebase/1/documents/10', async () => {
          deleteCalled = true
          documentsReturn = []
          return HttpResponse.json({ code: 200, message: 'ok', data: null })
        }),
      )

      const user = userEvent.setup()
      render(<KnowledgeBaseManagePage onUpload={() => {}} onChat={() => {}} />)

      expect(await screen.findByText('测试知识库')).toBeInTheDocument()

      await user.click(screen.getByTitle('文档列表'))
      expect(await screen.findByText('doc.pdf')).toBeInTheDocument()

      await user.click(screen.getByTitle('删除文档'))
      expect(await screen.findByText('确定删除')).toBeInTheDocument()

      await user.click(screen.getByText('确定删除'))

      await waitFor(() => {
        expect(deleteCalled).toBe(true)
      })
    })
  })

  describe('同库重复上传改用统一提示', () => {
    it('追加文档失败时不调用 window.alert，改用 toast 提示', async () => {
      mockWithDocuments()

      server.use(
        http.post('/api/knowledgebase/1/documents', () =>
          HttpResponse.json(
            { code: 409, message: '该知识库已存在同名文档' },
            { status: 409 },
          ),
        ),
      )

      const user = userEvent.setup()
      render(<KnowledgeBaseManagePage onUpload={() => {}} onChat={() => {}} />)

      expect(await screen.findByText('测试知识库')).toBeInTheDocument()

      await user.click(screen.getByTitle('文档列表'))
      expect(await screen.findByText('doc.pdf')).toBeInTheDocument()

      const addBtn = screen.getByText('追加文件')
      await user.click(addBtn)

      const fileInput = document.querySelector('input[type="file"][accept=".txt,.md,.pdf,.docx"]') as HTMLInputElement
      expect(fileInput).toBeTruthy()

      const file = new File(['test'], 'duplicate.pdf', { type: 'application/pdf' })
      await user.upload(fileInput, file)

      expect(alertSpy).not.toHaveBeenCalled()
      expect(await screen.findByText('该知识库已存在同名文档')).toBeInTheDocument()
    })
  })

  describe('文档面板轮询刷新 (Issue #68)', () => {
    it('面板展开且有非终态文档时，定时发出文档列表请求', async () => {
      const user = userEvent.setup()
      mockMountEndpoints()

      let docCallCount = 0
      server.use(
        http.get('/api/knowledgebase/1/documents', () => {
          docCallCount++
          return HttpResponse.json({
            code: 200,
            message: 'ok',
            data: [{ ...MOCK_DOC, vectorStatus: 'PENDING' }],
          })
        }),
      )

      render(<KnowledgeBaseManagePage onUpload={() => {}} onChat={() => {}} />)
      expect(await screen.findByText('测试知识库')).toBeInTheDocument()

      // 展开文档面板
      await user.click(screen.getByTitle('文档列表'))

      // 等待首次 loadDocuments 完成
      await waitFor(() => expect(docCallCount).toBeGreaterThanOrEqual(1))
      // 等待文档渲染
      expect(await screen.findByText('doc.pdf')).toBeInTheDocument()

      // 等待 5.5 秒 → 轮询应触发第二次
      await flush(5500)
      expect(docCallCount).toBeGreaterThanOrEqual(2)

      // 再等 5 秒 → 应第三次
      await flush(5000)
      expect(docCallCount).toBeGreaterThanOrEqual(3)
    }, 20000)

    it('所有文档到达终态后，轮询停止', async () => {
      const user = userEvent.setup()
      mockMountEndpoints()

      let docCallCount = 0
      server.use(
        http.get('/api/knowledgebase/1/documents', () => {
          docCallCount++
          if (docCallCount <= 1) {
            // 首次返回 PENDING
            return HttpResponse.json({
              code: 200,
              message: 'ok',
              data: [{ ...MOCK_DOC, vectorStatus: 'PENDING' }],
            })
          }
          // 后续返回 COMPLETED（终态）
          return HttpResponse.json({
            code: 200,
            message: 'ok',
            data: [{ ...MOCK_DOC, vectorStatus: 'COMPLETED' }],
          })
        }),
      )

      render(<KnowledgeBaseManagePage onUpload={() => {}} onChat={() => {}} />)
      expect(await screen.findByText('测试知识库')).toBeInTheDocument()

      await user.click(screen.getByTitle('文档列表'))
      await waitFor(() => expect(docCallCount).toBe(1))
      expect(await screen.findByText('doc.pdf')).toBeInTheDocument()

      // 等 5.5 秒 → 轮询触发第二次（返回 COMPLETED）
      await flush(5500)
      expect(docCallCount).toBe(2)

      // 再等 6 秒 → 不应再轮询（全部终态）
      await flush(6000)
      expect(docCallCount).toBe(2)
    }, 20000)

    it('面板关闭后，轮询停止', async () => {
      const user = userEvent.setup()
      mockMountEndpoints()

      let docCallCount = 0
      server.use(
        http.get('/api/knowledgebase/1/documents', () => {
          docCallCount++
          return HttpResponse.json({
            code: 200,
            message: 'ok',
            data: [{ ...MOCK_DOC, vectorStatus: 'PROCESSING' }],
          })
        }),
      )

      render(<KnowledgeBaseManagePage onUpload={() => {}} onChat={() => {}} />)
      expect(await screen.findByText('测试知识库')).toBeInTheDocument()

      // 展开
      await user.click(screen.getByTitle('文档列表'))
      await waitFor(() => expect(docCallCount).toBe(1))
      expect(await screen.findByText('doc.pdf')).toBeInTheDocument()

      // 等 5.5 秒 → 轮询触发
      await flush(5500)
      expect(docCallCount).toBe(2)

      // 关闭面板
      await user.click(screen.getByTitle('文档列表'))
      await flush(200) // 等 React 处理状态更新
      const countAfterClose = docCallCount

      // 等 6 秒 → 不应再有新请求
      await flush(6000)
      expect(docCallCount).toBe(countAfterClose)
    }, 20000)
  })
})
