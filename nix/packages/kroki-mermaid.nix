# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  stdenv,
  python311,
  mermaid-cli,
  makeWrapper,
  writeText,
  lib,
  port ? "8002",
  ...
}: let
  script = writeText "kroki-mermaid.py" ''
    import http.server
    import json
    import os
    import subprocess
    import tempfile

    class Handler(http.server.BaseHTTPRequestHandler):
      def log_message(self, fmt, *args):
        pass

      def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        fmt = self.path.split("?")[0].rstrip("/").rsplit("/", 1)[-1].lower()
        inp = out = None
        try:
          with tempfile.NamedTemporaryFile(suffix=".mmd", delete=False) as f:
            f.write(body)
            inp = f.name
          out = inp + "." + fmt
          r = subprocess.run(
            ["mmdc", "-i", inp, "-o", out],
            capture_output=True, timeout=25
          )
          if r.returncode != 0:
            msg = r.stderr.decode(errors="replace") or r.stdout.decode(errors="replace")
            self._error(400, msg)
            return
          with open(out, "rb") as f:
            data = f.read()
          ct = "image/svg+xml" if fmt == "svg" else "image/png"
          self.send_response(200)
          self.send_header("Content-Type", ct)
          self.send_header("Content-Length", str(len(data)))
          self.end_headers()
          self.wfile.write(data)
        except subprocess.TimeoutExpired:
          self._error(504, "mmdc timed out")
        except Exception as e:
          self._error(500, str(e))
        finally:
          for p in (inp, out):
            if p and os.path.exists(p):
              os.unlink(p)

      def _error(self, code, msg):
        body = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    port = int(os.environ.get("KROKI_MERMAID_PORT", "${port}"))
    print(f"kroki-mermaid listening on :{port}", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
  '';
in
  stdenv.mkDerivation {
    pname = "kroki-mermaid";
    version = "1";

    dontUnpack = true;
    dontBuild = true;

    nativeBuildInputs = [makeWrapper];

    installPhase = ''
      runHook preInstall
      mkdir -p $out/bin $out/libexec
      cp ${script} $out/libexec/kroki-mermaid.py
      makeWrapper ${python311}/bin/python3 $out/bin/kroki-mermaid \
        --add-flags "$out/libexec/kroki-mermaid.py" \
        --prefix PATH : ${lib.makeBinPath [mermaid-cli]}
      runHook postInstall
    '';
  }
