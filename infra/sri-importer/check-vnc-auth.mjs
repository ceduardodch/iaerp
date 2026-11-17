import { createConnection } from 'node:net'

const socket = createConnection({ host: '127.0.0.1', port: 5900 })
const timer = setTimeout(() => { socket.destroy(); process.exit(1) }, 5000)
let buffer = Buffer.alloc(0)
let greeted = false
socket.on('error', () => { clearTimeout(timer); process.exit(1) })
socket.on('data', (chunk) => {
  buffer = Buffer.concat([buffer, chunk])
  if (!greeted) {
    if (buffer.length < 12) return
    if (!buffer.subarray(0, 12).equals(Buffer.from('RFB 003.008\n'))) process.exit(1)
    buffer = buffer.subarray(12)
    greeted = true
    socket.write('RFB 003.008\n')
  }
  if (buffer.length < 2) return
  const count = buffer[0]
  if (buffer.length < count + 1) return
  const types = buffer.subarray(1, count + 1)
  clearTimeout(timer)
  socket.destroy()
  // RFB security 1 means unauthenticated access; 2 requires VNC authentication.
  if (count !== 1 || types[0] !== 2) process.exit(1)
  process.stdout.write('VNC authentication required.\n')
})
