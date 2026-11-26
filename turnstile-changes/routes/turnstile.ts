
import type { NextFunction, Request, Response } from 'express'

const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

interface TurnstileVerificationResponse {
  success: boolean
  hostname?: string
  action?: string
  'error-codes'?: string[]
}

export function verifyTurnstile () {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    const token = req.body?.turnstileToken
    const secret = process.env.TURNSTILE_SECRET

    // Reject requests without a token.
    if (typeof token !== 'string' || token.length === 0 || token.length > 2048) {
      res.status(400).json({
        error: {
          message: 'Turnstile token is missing or invalid.'
        }
      })
      return
    }

    // The secret must be configured on the backend.
    if (!secret) {
      console.error('Turnstile secret is not configured.')
      res.status(500).json({
        error: {
          message: 'CAPTCHA verification is not configured.'
        }
      })
      return
    }

    try {
      const response = await fetch(SITEVERIFY_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          secret,
          response: token
        }),
        signal: AbortSignal.timeout(10000)
      })

      if (!response.ok) {
        console.error('Turnstile Siteverify returned HTTP status:', response.status)
        res.status(502).json({
          error: {
            message: 'CAPTCHA verification service is unavailable.'
          }
        })
        return
      }

      const result = await response.json() as TurnstileVerificationResponse

      // Reject invalid, expired, or already-used tokens.
      if (!result.success) {
        console.warn('Turnstile verification failed:', result['error-codes'])
        res.status(403).json({
          error: {
            message: 'CAPTCHA verification failed. Please try again.'
          }
        })
        return
      }

      // Ensure the token was generated for the checkout action.
      if (result.action !== 'checkout') {
        console.warn('Turnstile action mismatch:', result.action)
        res.status(403).json({
          error: {
            message: 'CAPTCHA verification action is invalid.'
          }
        })
        return
      }

      // Only continue to checkout after successful verification.
      next()
    } catch (error) {
      console.error('Turnstile verification error:', error)
      res.status(502).json({
        error: {
          message: 'Could not verify CAPTCHA. Please try again.'
        }
      })
    }
  }
}
