import { setupServer } from 'msw/node'

/**
 * MSW（Node）服务器：前端行为测试的后端替身（ADR-0016 Phase 3）。
 *
 * 此处不预置任何 handler —— 每个测试用 `server.use(...)` 显式声明它依赖的后端契约，
 * 配合 setup.ts 的 `onUnhandledRequest: 'error'`，任何未声明的请求都会让测试失败，
 * 从而逼迫测试把"点了按钮该打哪个后端端点"写清楚（与竖切 / 契约守卫同源思想）。
 */
export const server = setupServer()
