//! Dependency-free container readiness probe. Run before application initialization.

use std::{
    env,
    io::{self, Read, Write},
    net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, TcpStream},
    time::{Duration, Instant},
};

const TIMEOUT: Duration = Duration::from_secs(2);
const MAX_STATUS_BYTES: usize = 512;

pub fn run() -> io::Result<()> {
    let address = match env::var("BIND_ADDRESS") {
        Ok(value) => value,
        Err(env::VarError::NotPresent) => "127.0.0.1:8080".to_owned(),
        Err(error) => return Err(io::Error::new(io::ErrorKind::InvalidInput, error)),
    };
    probe(probe_address(&address)?)
}

fn probe_address(value: &str) -> io::Result<SocketAddr> {
    let mut address: SocketAddr = value
        .parse()
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
    // Wildcard addresses are listener targets, not portable connection targets.
    if address.ip().is_unspecified() {
        address.set_ip(match address.ip() {
            IpAddr::V4(_) => Ipv4Addr::LOCALHOST.into(),
            IpAddr::V6(_) => Ipv6Addr::LOCALHOST.into(),
        });
    }
    Ok(address)
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "readiness probe timed out"))
}

fn probe(address: SocketAddr) -> io::Result<()> {
    let deadline = Instant::now() + TIMEOUT;
    let mut socket = TcpStream::connect_timeout(&address, remaining(deadline)?)?;
    socket.set_write_timeout(Some(remaining(deadline)?))?;
    write!(
        socket,
        "GET /ready HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n"
    )?;

    // Only the status line is needed; never allocate or download an unbounded body.
    // Recompute the deadline for every read so a drip-fed response cannot extend it.
    let mut response = [0_u8; MAX_STATUS_BYTES];
    let mut used = 0;
    while used < response.len() {
        socket.set_read_timeout(Some(remaining(deadline)?))?;
        let count = socket.read(&mut response[used..])?;
        if count == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "readiness response ended before its HTTP status line",
            ));
        }
        used += count;
        if let Some(end) = response[..used].windows(2).position(|pair| pair == b"\r\n") {
            return check_status(&response[..end]);
        }
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "readiness HTTP status line is too long",
    ))
}

fn check_status(line: &[u8]) -> io::Result<()> {
    if (line.starts_with(b"HTTP/1.1 200 ") || line.starts_with(b"HTTP/1.0 200 "))
        && line[13..]
            .iter()
            .all(|byte| *byte == b'\t' || *byte >= b' ' && *byte != 0x7f)
    {
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "readiness endpoint did not return HTTP 200",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{net::TcpListener, thread};

    #[test]
    fn wildcard_bind_addresses_use_the_corresponding_loopback() {
        for (bind, target) in [
            ("0.0.0.0:8080", "127.0.0.1:8080"),
            ("[::]:9090", "[::1]:9090"),
            ("127.0.0.1:1234", "127.0.0.1:1234"),
            ("[::1]:8080", "[::1]:8080"),
        ] {
            assert_eq!(probe_address(bind).unwrap().to_string(), target);
        }
        assert!(probe_address("localhost:8080").is_err());
        assert!(probe_address("not a socket address").is_err());
    }

    #[test]
    fn only_a_complete_http_200_status_is_ready() {
        for ready in [b"HTTP/1.1 200 OK".as_slice(), b"HTTP/1.0 200 "] {
            assert!(check_status(ready).is_ok());
        }
        for unavailable in [
            b"HTTP/1.1 503 Service Unavailable".as_slice(),
            b"HTTP/1.1 302 Found",
            b"HTTP/1.1 2000 OK",
            b"HTTP/1.1 200",
            b"HTTP/1.1 200 \0",
            b"HTTP/2 200 OK",
            b"garbage 200 OK",
        ] {
            assert!(check_status(unavailable).is_err(), "{unavailable:?}");
        }
    }

    #[test]
    fn probe_requests_readiness_and_rejects_failed_or_unbounded_responses() {
        for (response, ready) in [
            (
                b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n".to_vec(),
                true,
            ),
            (b"HTTP/1.1 503 Service Unavailable\r\n\r\n".to_vec(), false),
            (b"HTTP/1.1 200 OK".to_vec(), false),
            (vec![b'X'; MAX_STATUS_BYTES], false),
        ] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let address = listener.local_addr().unwrap();
            let server = thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                socket.set_read_timeout(Some(TIMEOUT)).unwrap();
                let mut request = [0_u8; 256];
                let count = socket.read(&mut request).unwrap();
                assert!(request[..count].starts_with(b"GET /ready HTTP/1.1\r\n"));
                socket.write_all(&response).unwrap();
            });
            assert_eq!(probe(address).is_ok(), ready);
            server.join().unwrap();
        }
    }
}
