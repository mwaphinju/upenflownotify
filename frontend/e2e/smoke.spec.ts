import { expect, test } from '@playwright/test'

const MAILHOG_API = process.env.E2E_MAILHOG_URL ?? 'http://127.0.0.1:8025/api/v2/messages'
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? ''
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? ''

/** Polls Mailhog's REST API for the most recent OTP email to `recipient` and extracts the
 * 6-digit code from its body (see backend/app/email.py's send_otp_email wording). */
async function fetchLatestOtp(recipient: string): Promise<string> {
  for (let attempt = 0; attempt < 20; attempt++) {
    const response = await fetch(MAILHOG_API)
    const data = await response.json()
    const match = (data.items ?? []).find((item: { Content: { Headers: { To: string[] } } }) =>
      item.Content.Headers.To?.some((to: string) => to.toLowerCase().includes(recipient.toLowerCase())),
    )
    if (match) {
      const body: string = match.Content.Body
      const code = body.match(/verification code is (\d{6})/)
      if (code) return code[1]
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`No OTP email arrived for ${recipient} within the polling window`)
}

test.skip(!EMAIL || !PASSWORD, 'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD not set')

test('sign in with OTP, view the dashboard, navigate to Rules, and sign out', async ({ page }) => {
  await page.goto('/')

  await page.fill('#email', EMAIL)
  await page.fill('#password', PASSWORD)
  await page.getByRole('button', { name: /continue securely/i }).click()

  await expect(page.getByText(/check your inbox/i)).toBeVisible()
  const otp = await fetchLatestOtp(EMAIL)
  await page.fill('#otp-code', otp)
  await page.getByRole('button', { name: /verify and sign in/i }).click()

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await page.getByRole('button', { name: 'Rules' }).click()
  await expect(page.getByRole('heading', { name: 'Notification rules' })).toBeVisible()

  await page.getByRole('button', { name: /sign out/i }).click()
  await expect(page.locator('#email')).toBeVisible()
})
