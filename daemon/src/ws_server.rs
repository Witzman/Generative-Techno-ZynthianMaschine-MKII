use std::io;
use std::net::TcpListener;
use std::sync::mpsc;
use tungstenite::{accept, Message};

use crate::ws_types::{DeviceEvent, WsCommand};

pub fn start(
    bind: String,
    cmd_tx: mpsc::Sender<WsCommand>,
    event_rx: mpsc::Receiver<DeviceEvent>,
) {
    std::thread::spawn(move || run(bind, cmd_tx, event_rx));
}

/// The port is fixed; only the address is configurable.
const PORT: u16 = 9001;
pub const LOOPBACK: &str = "127.0.0.1";

fn run(bind: String, cmd_tx: mpsc::Sender<WsCommand>, event_rx: mpsc::Receiver<DeviceEvent>) {
    let listener = match TcpListener::bind((bind.as_str(), PORT)) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("error: WebSocket server failed to bind {}:{}: {}", bind, PORT, e);
            return;
        }
    };
    if bind != LOOPBACK {
        // SAID OUT LOUD, since 2026-09-03. This socket takes commands that
        // remap the pads' MIDI notes and WRITE THEM TO DISK, and it has no
        // authentication of any kind; the daemon runs as root. That is a
        // reasonable default only for as long as somebody knows it is the
        // default, and nothing said so before this line.
        eprintln!(
            "warning: the WebSocket editor is listening on {}:{} with NO \
             authentication - anything on this network can remap the pads. \
             Set \"ws_bind\": \"127.0.0.1\" in maschine.json to close it.",
            bind, PORT);
    }
    eprintln!("web editor: open http://<pi-ip>:9000  (ws://{}:{})", bind, PORT);

    for stream in listener.incoming() {
        let stream = match stream {
            Ok(s) => s,
            Err(_) => continue,
        };
        let mut ws = match accept(stream) {
            Ok(ws) => ws,
            Err(e) => {
                eprintln!("ws: handshake failed: {}", e);
                continue;
            }
        };
        if let Err(e) = ws.get_mut().set_nonblocking(true) {
            eprintln!("ws: cannot set non-blocking: {}", e);
            continue;
        }
        // THE BACKLOG IS NOT HISTORY. The event channel is bounded and is
        // drained only here, so whatever is in it when a client arrives is
        // whatever happened before anyone was looking - up to 256 presses that
        // would then trickle out at one per 5 ms and read as live.
        while event_rx.try_recv().is_ok() {}
        let _ = cmd_tx.send(WsCommand::RequestConfig);

        loop {
            match ws.read() {
                Ok(Message::Text(text)) => {
                    if let Ok(cmd) = serde_json::from_str::<WsCommand>(&text) {
                        let _ = cmd_tx.send(cmd);
                    }
                }
                Ok(Message::Close(_)) | Err(tungstenite::Error::ConnectionClosed) => break,
                Err(tungstenite::Error::Io(ref e)) if e.kind() == io::ErrorKind::WouldBlock => {}
                Err(_) => break,
                _ => {}
            }

            match event_rx.try_recv() {
                Ok(event) => {
                    let json = serde_json::to_string(&event).unwrap();
                    if ws.send(Message::Text(json)).is_err() {
                        break;
                    }
                }
                Err(mpsc::TryRecvError::Empty) => {}
                Err(mpsc::TryRecvError::Disconnected) => return,
            }

            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
}
