package local.veridex.capture;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.ScrollView;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URI;
import java.net.URL;

public class MainActivity extends Activity {
    private TextView status;
    private EditText pairingUrl;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(20 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad, pad, pad);
        TextView title = new TextView(this);
        title.setText("Veridex Capture"); title.setTextSize(24);
        layout.addView(title);
        TextView instructions = new TextView(this);
        instructions.setText("Scan the pairing QR code in the Betting room, or paste the one-time pairing URL. Screen capture is not available in this version.");
        layout.addView(instructions);
        Button scan = new Button(this); scan.setText("Scan pairing code"); layout.addView(scan);
        pairingUrl = new EditText(this);
        pairingUrl.setSingleLine(true);
        pairingUrl.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        pairingUrl.setHint("http://192.168.x.x:8765/pair?token=…");
        layout.addView(pairingUrl, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        Button pair = new Button(this); pair.setText("Pair with Veridex"); layout.addView(pair);
        status = new TextView(this); layout.addView(status);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.addView(layout);
        setContentView(scroll);
        Button clear = new Button(this); clear.setText("Clear pairing URL");
        layout.addView(clear);
        clear.setOnClickListener(v -> { pairingUrl.setText(""); status.setText(""); });
        scan.setOnClickListener(v -> GmsBarcodeScanning.getClient(this).startScan()
            .addOnSuccessListener(barcode -> {
                String value = barcode.getRawValue();
                if (value == null) { status.setText("The code was empty. Try again."); return; }
                beginPair(value.trim(), pair, scan);
            })
            .addOnCanceledListener(() -> status.setText("Scanning cancelled."))
            .addOnFailureListener(error -> status.setText("Scanner unavailable. Check Google Play services and try again.")));
        pair.setOnClickListener(v -> {
            String input = pairingUrl.getText().toString().trim();
            beginPair(input, pair, scan);
        });
    }

    private void beginPair(String input, Button pairButton, Button scanButton) {
        pairButton.setEnabled(false); scanButton.setEnabled(false); status.setText("Pairing…");
        new Thread(() -> {
            String result;
            try { pair(input); result = "Paired. Capture is not available yet."; }
            catch (IllegalArgumentException error) { result = error.getMessage(); }
            catch (java.net.URISyntaxException error) { result = "Pairing URL is malformed. Scan the QR code again."; }
            catch (java.net.SocketTimeoutException error) { result = "Connection timed out. Check Wi-Fi and the PC firewall."; }
            catch (java.io.IOException error) { result = "Could not connect to Veridex. Check Wi-Fi and the PC firewall."; }
            catch (IllegalStateException error) { result = error.getMessage(); }
            catch (Exception error) { result = "Pairing failed (" + error.getClass().getSimpleName() + ")."; }
            final String message = result;
            runOnUiThread(() -> { pairingUrl.setText(""); status.setText(message); pairButton.setEnabled(true); scanButton.setEnabled(true); });
        }).start();
    }

    private void pair(String input) throws Exception {
        URI uri = new URI(input);
        String host = uri.getHost();
        if (!"http".equalsIgnoreCase(uri.getScheme())) throw new IllegalArgumentException("Scanned code does not have an HTTP pairing address.");
        if (host == null || !host.matches("[0-9.]+")) throw new IllegalArgumentException("Scanned code does not contain a numeric LAN address.");
        if (uri.getPort() != 8765) throw new IllegalArgumentException("Scanned code uses the wrong port for Veridex pairing.");
        if (!"/pair".equals(uri.getPath())) throw new IllegalArgumentException("Scanned code is not a pairing link. Use Show pairing QR code in the trade journal.");
        if (uri.getUserInfo() != null || uri.getFragment() != null) throw new IllegalArgumentException("Scanned pairing link has unexpected extra fields.");
        if (uri.getRawQuery() == null || !uri.getRawQuery().matches("token=[A-Za-z0-9_-]+")) throw new IllegalArgumentException("The pairing token is missing or incomplete. Scan a fresh QR code.");
        if (!InetAddress.getByName(host).isSiteLocalAddress()) throw new IllegalArgumentException("The pairing address is not a private network address.");
        HttpURLConnection conn = (HttpURLConnection)new URL(input).openConnection();
        conn.setConnectTimeout(5000); conn.setReadTimeout(5000); conn.setInstanceFollowRedirects(false);
        try {
            int response = conn.getResponseCode();
            if (response == 401) throw new IllegalStateException("Pairing link expired or was already used. Generate a fresh link.");
            if (response != 303) throw new IllegalStateException("Veridex returned HTTP " + response + " while pairing.");
            String cookie = conn.getHeaderField("Set-Cookie");
            if (cookie == null || !cookie.startsWith("veridex_remote_session=")) throw new IllegalStateException("Veridex did not return a pairing session.");
            String sessionCookie = cookie.split(";", 2)[0];
            getSharedPreferences("pairing", MODE_PRIVATE).edit().putString("server", "http://" + host + ":8765").putString("cookie", sessionCookie).apply();
        } finally { conn.disconnect(); }
    }
}
