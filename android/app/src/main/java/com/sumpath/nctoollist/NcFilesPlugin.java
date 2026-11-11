package com.sumpath.nctoollist;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Context;
import android.os.Build;
import android.os.Environment;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.util.Base64;

import androidx.activity.result.ActivityResult;
import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * NC 파일 열기/저장 — Storage Access Framework(SAF).
 * - openDocument: 파일 선택기에서 고른 파일을 읽고, 같은 파일에 다시 쓸 수 있게 영구 권한을 받는다.
 * - readDocument / writeDocument / statDocument: uri 로 읽기·덮어쓰기·크기와 수정 시각.
 * - createDocument: "다른 이름으로 저장".
 * - takeIncoming: 다른 앱(파일 앱·메일·메신저)에서 "Sum Path로 열기"/공유로 받은 파일.
 * - saveBackup: 덮어쓰기 전에 원래 내용을 앱 폴더(backup)에 .bak 로 남긴다.
 */
@CapacitorPlugin(name = "NcFiles")
public class NcFilesPlugin extends Plugin {
    private Uri pendingIncoming = null;

    @Override
    public void load() {
        captureIncoming(getActivity().getIntent());
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        super.handleOnNewIntent(intent);
        captureIncoming(intent);
        if (pendingIncoming != null) notifyListeners("incoming", new JSObject());
    }

    private void captureIncoming(Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        Uri uri = null;
        if (Intent.ACTION_VIEW.equals(action)) {
            uri = intent.getData();
        } else if (Intent.ACTION_SEND.equals(action)) {
            uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
        }
        if (uri != null) {
            pendingIncoming = uri;
            intent.setAction(Intent.ACTION_MAIN); // 한 번만 처리한다
        }
    }

    private static String b64(byte[] bytes) {
        return Base64.encodeToString(bytes, Base64.NO_WRAP);
    }

    private byte[] readAll(Uri uri) throws IOException {
        ContentResolver cr = getContext().getContentResolver();
        try (InputStream in = cr.openInputStream(uri)) {
            if (in == null) throw new IOException("열 수 없는 파일입니다");
            ByteArrayOutputStream out = new ByteArrayOutputStream(Math.max(8192, in.available()));
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }

    private JSObject stat(Uri uri) {
        JSObject o = new JSObject();
        o.put("uri", uri.toString());
        String name = null;
        long size = -1;
        long modified = 0;
        try (Cursor c = getContext().getContentResolver().query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (i >= 0) name = c.getString(i);
                i = c.getColumnIndex(OpenableColumns.SIZE);
                if (i >= 0 && !c.isNull(i)) size = c.getLong(i);
                i = c.getColumnIndex(DocumentsContract.Document.COLUMN_LAST_MODIFIED);
                if (i >= 0 && !c.isNull(i)) modified = c.getLong(i);
            }
        } catch (Exception ignored) {
            // 일부 제공자는 조회를 막는다 — 이름만 uri 에서 뽑는다
        }
        if (name == null) {
            String last = uri.getLastPathSegment();
            name = last == null ? "program.nc" : last.substring(last.lastIndexOf('/') + 1);
        }
        boolean writable = getContext().checkCallingOrSelfUriPermission(uri, Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
        o.put("name", name);
        o.put("size", size);
        o.put("modified", modified);
        o.put("writable", writable);
        return o;
    }

    private JSObject describeWithData(Uri uri) throws IOException {
        byte[] bytes = readAll(uri);
        JSObject o = stat(uri);
        o.put("data", b64(bytes));
        if (o.optLong("size", -1) < 0) o.put("size", bytes.length);
        return o;
    }

    // ---------------------------------------------------------------- 열기
    @PluginMethod
    public void openDocument(PluginCall call) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        // 외부 저장장치(USB·SD)가 꽂혀 있으면 선택기를 그 장치에서 시작한다. 없으면 기존대로.
        Uri external = externalStorageRoot();
        if (external != null) intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI, external);
        startActivityForResult(call, intent, "openResult");
    }

    /** 마운트된 이동식 저장장치(USB·SD)의 루트 문서 주소. 없으면 null */
    private Uri externalStorageRoot() {
        try {
            StorageManager sm = (StorageManager) getContext().getSystemService(Context.STORAGE_SERVICE);
            if (sm == null) return null;
            for (StorageVolume v : sm.getStorageVolumes()) {
                if (v.isPrimary() || !v.isRemovable() || !Environment.MEDIA_MOUNTED.equals(v.getState())) continue;
                if (Build.VERSION.SDK_INT >= 29) {
                    Intent i = v.createOpenDocumentTreeIntent();
                    Uri u = i.getParcelableExtra(DocumentsContract.EXTRA_INITIAL_URI);
                    if (u != null) return u;
                }
                String uuid = v.getUuid();
                if (uuid != null) return DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", uuid + ":");
            }
        } catch (RuntimeException ignored) {
            // 저장장치 정보를 못 읽으면 기존 위치로 연다
        }
        return null;
    }

    @ActivityCallback
    private void openResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        Intent data = result.getData();
        if (result.getResultCode() != Activity.RESULT_OK || data == null || data.getData() == null) {
            JSObject o = new JSObject();
            o.put("cancelled", true);
            call.resolve(o);
            return;
        }
        Uri uri = data.getData();
        try {
            getContext().getContentResolver().takePersistableUriPermission(uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        } catch (Exception ignored) {
            // 쓰기 권한을 못 받으면 읽기 전용으로 둔다(저장은 다른 이름으로)
            try {
                getContext().getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } catch (Exception ignoredAgain) {
                // 영구 권한이 없어도 지금은 읽을 수 있다
            }
        }
        try {
            call.resolve(describeWithData(uri));
        } catch (IOException e) {
            call.reject("열기 실패: " + e.getMessage());
        }
    }

    @PluginMethod
    public void readDocument(PluginCall call) {
        String uri = call.getString("uri");
        if (uri == null) {
            call.reject("uri 가 없습니다");
            return;
        }
        try {
            call.resolve(describeWithData(Uri.parse(uri)));
        } catch (IOException | SecurityException e) {
            call.reject("읽기 실패: " + e.getMessage());
        }
    }

    @PluginMethod
    public void statDocument(PluginCall call) {
        String uri = call.getString("uri");
        if (uri == null) {
            call.reject("uri 가 없습니다");
            return;
        }
        try {
            JSObject o = stat(Uri.parse(uri));
            if (o.optLong("size", -1) < 0 && o.optLong("modified", 0) == 0) {
                // 조회할 수 없으면(지워졌거나 권한 없음) 열어 본다
                try (InputStream in = getContext().getContentResolver().openInputStream(Uri.parse(uri))) {
                    if (in == null) throw new IOException("없음");
                }
            }
            call.resolve(o);
        } catch (IOException | SecurityException e) {
            JSObject o = new JSObject();
            o.put("missing", true);
            call.resolve(o);
        }
    }

    // ---------------------------------------------------------------- 저장
    @PluginMethod
    public void writeDocument(PluginCall call) {
        String uri = call.getString("uri");
        String data = call.getString("data");
        if (uri == null || data == null) {
            call.reject("uri 또는 data 가 없습니다");
            return;
        }
        try {
            byte[] bytes = Base64.decode(data, Base64.DEFAULT);
            try (OutputStream out = getContext().getContentResolver().openOutputStream(Uri.parse(uri), "wt")) {
                if (out == null) throw new IOException("쓸 수 없는 파일입니다");
                out.write(bytes);
            }
            call.resolve(stat(Uri.parse(uri)));
        } catch (IOException | SecurityException | IllegalArgumentException e) {
            call.reject("저장 실패: " + e.getMessage());
        }
    }

    @PluginMethod
    public void createDocument(PluginCall call) {
        String name = call.getString("name", "program.nc");
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/octet-stream");
        intent.putExtra(Intent.EXTRA_TITLE, name);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(call, intent, "createResult");
    }

    @ActivityCallback
    private void createResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        Intent data = result.getData();
        if (result.getResultCode() != Activity.RESULT_OK || data == null || data.getData() == null) {
            JSObject o = new JSObject();
            o.put("cancelled", true);
            call.resolve(o);
            return;
        }
        Uri uri = data.getData();
        try {
            getContext().getContentResolver().takePersistableUriPermission(uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        } catch (Exception ignored) {
            // 영구 권한이 없어도 이번 저장은 된다
        }
        try {
            byte[] bytes = Base64.decode(call.getString("data", ""), Base64.DEFAULT);
            try (OutputStream out = getContext().getContentResolver().openOutputStream(uri, "wt")) {
                if (out == null) throw new IOException("쓸 수 없는 위치입니다");
                out.write(bytes);
            }
            call.resolve(stat(uri));
        } catch (IOException | SecurityException | IllegalArgumentException e) {
            call.reject("저장 실패: " + e.getMessage());
        }
    }

    /** 덮어쓰기 전 원본을 앱 폴더 backup/<이름>.bak 에 남긴다(SAF 로는 같은 폴더에 만들 수 없다). */
    @PluginMethod
    public void saveBackup(PluginCall call) {
        String name = call.getString("name", "program.nc");
        String data = call.getString("data");
        if (data == null) {
            call.reject("data 가 없습니다");
            return;
        }
        try {
            File dir = new File(getContext().getExternalFilesDir(null), "backup");
            if (!dir.exists() && !dir.mkdirs()) throw new IOException("백업 폴더를 만들 수 없습니다");
            String safe = name.replaceAll("[\\\\/:*?\"<>|]", "_");
            File file = new File(dir, safe + ".bak");
            try (FileOutputStream out = new FileOutputStream(file)) {
                out.write(Base64.decode(data, Base64.DEFAULT));
            }
            JSObject o = new JSObject();
            o.put("path", file.getAbsolutePath());
            call.resolve(o);
        } catch (IOException | IllegalArgumentException e) {
            call.reject("백업 실패: " + e.getMessage());
        }
    }

    // ---------------------------------------------------------------- PDF 열기(저장은 PDF 앱에서 사용자가 정한다)
    @PluginMethod
    public void openPdf(PluginCall call) {
        String name = call.getString("name", "toollist.pdf");
        String data = call.getString("data");
        if (data == null) {
            call.reject("data 가 없습니다");
            return;
        }
        try {
            File dir = new File(getContext().getCacheDir(), "pdf");
            if (!dir.exists() && !dir.mkdirs()) throw new IOException("임시 폴더를 만들 수 없습니다");
            String safe = name.replaceAll("[\\/:*?\"<>|]", "_");
            if (!safe.toLowerCase().endsWith(".pdf")) safe = safe + ".pdf";
            File file = new File(dir, safe);
            try (FileOutputStream out = new FileOutputStream(file)) {
                out.write(Base64.decode(data, Base64.DEFAULT));
            }
            Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", file);
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, "application/pdf");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(Intent.createChooser(intent, "PDF 열기").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            call.resolve();
        } catch (IOException | IllegalArgumentException | android.content.ActivityNotFoundException e) {
            call.reject("PDF 열기 실패: " + e.getMessage());
        }
    }

    // ---------------------------------------------------------------- 다른 앱에서 열기
    @PluginMethod
    public void takeIncoming(PluginCall call) {
        JSObject o = new JSObject();
        if (pendingIncoming == null) {
            o.put("none", true);
            call.resolve(o);
            return;
        }
        Uri uri = pendingIncoming;
        pendingIncoming = null;
        try {
            call.resolve(describeWithData(uri));
        } catch (IOException | SecurityException e) {
            call.reject("열기 실패: " + e.getMessage());
        }
    }
}
