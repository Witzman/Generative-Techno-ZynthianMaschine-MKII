use std::io;
use std::net::TcpListener;
use std::sync::mpsc;
use tungstenite::{accept, Message};

use crate::ws_types::{DeviceEvent, WsCommand};

pub fn start(cmd_tx: mpsc::Sender<WsCommand>, event_rx: mpsc::Receiver<DeviceEvent>) {
    std::thread::spawn(move || run(cmd_tx, event_rx));
}

fn run(cmd_tx: mpsc::Sender<WsCommand>, event_rx: mpsc::Receiver<DeviceEvent>) {
    let listener = match TcpListener::bind("0.0.0.0:9001") {
        Ok(l) => l,
        Err(e) => {
            eprintln!("error: WebSocket server failed to bind on port 9001: {}", e);
            return;
        }
    };
    eprintln!("web editor: open http://<pi-ip>:9000  (ws://0.0.0.0:9001)");

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
        ws.get_mut().set_nonblocking(true).unwrap();
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
