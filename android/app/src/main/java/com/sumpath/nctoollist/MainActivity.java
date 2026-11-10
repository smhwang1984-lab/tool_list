package com.sumpath.nctoollist;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(NcFilesPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
