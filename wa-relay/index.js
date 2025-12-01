const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');

const GROUP_NAME = 'Terra Reports';  // group name to forward into
const BOT_CHAT_NAME = 'Terra Bot';   // name of the chat with WABA bot (as seen from number 79898142076)

const client = new Client({
    authStrategy: new LocalAuth({
        clientId: 'terra-relay-session',
    }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
        ],
    },
});

client.on('qr', (qr) => {
    console.log('Scan the QR with phone number 79898142076:');
    qrcode.generate(qr, { small: true });
});

client.on('ready', async () => {
    console.log('Relay client is ready.');
});

async function getGroupChat() {
    const chats = await client.getChats();
    const group = chats.find(
        (chat) => chat.isGroup && chat.name === GROUP_NAME
    );
    if (!group) {
        console.error(`Group "${GROUP_NAME}" not found.`);
        return null;
    }
    return group;
}

client.on('message', async (msg) => {
    try {
        const chat = await msg.getChat();

        // Listen only to messages received from the bot chat
        if (!chat.isGroup && chat.name === BOT_CHAT_NAME && !msg.fromMe) {
            const text = msg.body.trim();
            if (!text) return;

            console.log('New report from bot → forwarding to group...');

            const group = await getGroupChat();
            if (!group) return;

            await client.sendMessage(group.id._serialized, text);

            console.log('Report successfully forwarded.');
        }
    } catch (err) {
        console.error('Error processing message:', err);
    }
});

client.initialize();
