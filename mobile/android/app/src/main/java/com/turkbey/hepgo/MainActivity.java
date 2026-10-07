package com.turkbey.hepgo;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(IncomingCallPlugin.class);   // gelen arama tam-ekran bildirimi (voice.js kullanır)
        super.onCreate(savedInstanceState);
    }
}
