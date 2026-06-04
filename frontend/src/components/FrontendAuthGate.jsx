import { useEffect, useState } from 'react'
import { LockKeyhole, Send, ShieldCheck } from 'lucide-react'
import {
  clearFrontendSessionToken,
  getFrontendSessionToken,
  setFrontendSessionToken,
} from '../api_shared'
import {
  requestFrontendAuthCode,
  verifyFrontendAuthCode,
} from '../api_strategic'

export default function FrontendAuthGate({ children }) {
  const authDisabled = import.meta.env.VITE_ORACLE_FRONTEND_AUTH_ENABLED === 'false'
  const [authenticated, setAuthenticated] = useState(authDisabled || Boolean(getFrontendSessionToken()))
  const [code, setCode] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [verifying, setVerifying] = useState(false)

  useEffect(() => {
    const handleExpired = () => setAuthenticated(false)
    window.addEventListener('oracle-auth-expired', handleExpired)
    return () => window.removeEventListener('oracle-auth-expired', handleExpired)
  }, [])

  if (authenticated) return children

  const requestCode = async () => {
    setSending(true)
    setError('')
    try {
      clearFrontendSessionToken()
      const result = await requestFrontendAuthCode()
      const expiry = result?.expires_at ? new Date(result.expires_at).toLocaleTimeString() : '5 minutes'
      setStatus(`Code sent to Oracle Telegram. Expires at ${expiry}.`)
    } catch (err) {
      setError(err.message || 'Could not send login code')
      setStatus('')
    } finally {
      setSending(false)
    }
  }

  const verifyCode = async (event) => {
    event.preventDefault()
    setVerifying(true)
    setError('')
    try {
      const result = await verifyFrontendAuthCode(code.trim())
      setFrontendSessionToken(result.token)
      setAuthenticated(true)
    } catch (err) {
      setError(err.message || 'Invalid or expired code')
    } finally {
      setVerifying(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4">
      <section className="w-full max-w-md rounded-lg border border-gray-800 bg-gray-900 p-6 shadow-2xl">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-oracle-600/20 text-oracle-400">
            <LockKeyhole className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">Oracle Access</h1>
            <p className="text-sm text-gray-400">Telegram one-time code required</p>
          </div>
        </div>

        <button
          type="button"
          onClick={requestCode}
          disabled={sending}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-oracle-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-oracle-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Send className="h-4 w-4" />
          {sending ? 'Sending code...' : 'Send code to Telegram'}
        </button>

        <form onSubmit={verifyCode} className="mt-5 space-y-3">
          <label className="block text-sm font-medium text-gray-300" htmlFor="oracle-code">
            One-time code
          </label>
          <input
            id="oracle-code"
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            className="w-full rounded-lg border border-gray-700 bg-gray-950 px-4 py-3 text-lg text-white outline-none transition placeholder:text-gray-600 focus:border-oracle-500"
          />
          <button
            type="submit"
            disabled={verifying || code.trim().length < 4}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2.5 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <ShieldCheck className="h-4 w-4" />
            {verifying ? 'Verifying...' : 'Unlock Oracle'}
          </button>
        </form>

        {status && <p className="mt-4 text-sm text-emerald-300">{status}</p>}
        {error && <p className="mt-4 text-sm text-red-300">{error}</p>}
      </section>
    </main>
  )
}
