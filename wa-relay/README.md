# WhatsApp Relay Service

This service automatically forwards messages from the Terra Bot WhatsApp chat to the Terra Reports group.

## Installation

Install Node.js dependencies:

```bash
npm install
```

## Running Manually

To run the relay manually:

```bash
node index.js
```

When you first run the service, a QR code will appear in the terminal. Scan this QR code with phone number **79898142076** using WhatsApp on your phone:

1. Open WhatsApp on your phone
2. Go to Settings → Linked Devices
3. Tap "Link a Device"
4. Scan the QR code displayed in the terminal

Once authenticated, the service will start forwarding messages automatically.

## Running with PM2 (Auto-start)

To run the service as a background process that automatically restarts:

1. Install PM2 globally:
```bash
npm install -g pm2
```

2. Start the relay service:
```bash
pm2 start index.js --name terra-wa-relay
```

3. Save the PM2 process list:
```bash
pm2 save
```

4. Configure PM2 to start on system boot:
```bash
pm2 startup
```

Follow the instructions provided by the `pm2 startup` command (you may need to run a command with sudo/administrator privileges).

## PM2 Management Commands

- View status: `pm2 status`
- View logs: `pm2 logs terra-wa-relay`
- Restart: `pm2 restart terra-wa-relay`
- Stop: `pm2 stop terra-wa-relay`
- Remove: `pm2 delete terra-wa-relay`

## Configuration

The service is configured to:
- Forward messages from chat: **Terra Bot**
- To group: **Terra Reports**
- Using phone number: **79898142076**

To change these settings, edit the constants at the top of `index.js`:
- `GROUP_NAME` - target group name
- `BOT_CHAT_NAME` - source chat name
