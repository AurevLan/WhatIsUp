import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  apiBaseUrl,
  wsBaseUrl,
  setServerUrl,
  clearServerUrl,
  isConfigured,
  isNative,
} from '../serverConfig'

describe('serverConfig', () => {
  beforeEach(() => {
    localStorage.clear()
    delete window.Capacitor
  })

  afterEach(() => {
    localStorage.clear()
    delete window.Capacitor
  })

  it('web build defaults to relative /api/v1', () => {
    expect(isNative()).toBe(false)
    expect(apiBaseUrl()).toBe('/api/v1')
    expect(isConfigured()).toBe(true)
  })

  it('native build without stored url is not configured', () => {
    window.Capacitor = { isNativePlatform: () => true }
    expect(isNative()).toBe(true)
    expect(isConfigured()).toBe(false)
  })

  it('setServerUrl stores trimmed url and apiBaseUrl uses it', () => {
    setServerUrl('  https://monitoring.example.com/  ')
    expect(localStorage.getItem('whatisup_server_url')).toBe('https://monitoring.example.com')
    expect(apiBaseUrl()).toBe('https://monitoring.example.com/api/v1')
  })

  it('setServerUrl rejects empty or non-http urls', () => {
    expect(() => setServerUrl('')).toThrow()
    expect(() => setServerUrl('   ')).toThrow()
    expect(() => setServerUrl('ftp://x.tld')).toThrow()
    expect(() => setServerUrl('example.com')).toThrow()
  })

  it('wsBaseUrl rewrites http→ws and https→wss', () => {
    setServerUrl('http://localhost:8000')
    expect(wsBaseUrl()).toBe('ws://localhost:8000')
    setServerUrl('https://m.example.com')
    expect(wsBaseUrl()).toBe('wss://m.example.com')
  })

  it('clearServerUrl removes the stored url', () => {
    setServerUrl('https://x.tld')
    clearServerUrl()
    expect(localStorage.getItem('whatisup_server_url')).toBeNull()
  })

  it('native + configured → isConfigured true', () => {
    window.Capacitor = { isNativePlatform: () => true }
    setServerUrl('https://m.example.com')
    expect(isConfigured()).toBe(true)
    expect(apiBaseUrl()).toBe('https://m.example.com/api/v1')
  })
})
