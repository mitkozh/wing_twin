/*
 * Wing Digital Twin - Unity WebSocket Client
 * Receives {strain, forces, stress_field, deformation_field, damage, confidence, speed, led_state, maintenance_alert}
 * from Python WebSocket via force-reconstruction pipeline.
 *
 * Required Unity package: NativeWebSocket
 *   Window > Package Manager > Add package from git URL:
 *   https://github.com/NaMi-Design/NativeWebSocket.git?path=/package
 */

using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using NativeWebSocket;

public class WingDigitalTwin : MonoBehaviour
{
    [Header("Connection")]
    [SerializeField] private string serverUrl = "ws://localhost:8765";

    [Header("HUD")]
    [SerializeField] private Slider damageSlider;
    [SerializeField] private Text damageLabel;
    [SerializeField] private Text speedLabel;
    [SerializeField] private Text confidenceLabel;
    [SerializeField] private Image ledImage;
    [SerializeField] private Text alertLabel;

    [Header("Wing Visualization")]
    [SerializeField] private Renderer wingRenderer;
    [SerializeField] private Gradient stressGradient;

    [Header("LED Colors")]
    [SerializeField] private Color greenColor = new Color(0.1f, 1.0f, 0.1f);
    [SerializeField] private Color yellowColor = new Color(1.0f, 0.9f, 0.1f);
    [SerializeField] private Color redColor = new Color(1.0f, 0.1f, 0.1f);

    private WebSocket ws;
    private bool connected = false;

    private float currentDamage = 0f;
    private int currentSpeed = 100;
    private string currentState = "green";
    private float currentConfidence = 100f;
    private bool maintenanceAlert = false;
    private float[] stressField = Array.Empty<float>();
    private float[] deformationField = Array.Empty<float>();
    private float ledFlashTimer = 0f;
    private bool ledFlash = false;

    private readonly System.Collections.Generic.Queue<Action> mainThreadQueue =
        new System.Collections.Generic.Queue<Action>();

    async void Start()
    {
        await ConnectAsync();
    }

    async Task ConnectAsync()
    {
        try
        {
            ws = WebSocketFactory.CreateInstance(WebSocketFactory.WSType.WSSECURE, serverUrl);
            ws.OnOpen += () =>
            {
                connected = true;
                Debug.Log("[WS] Connected");
            };
            ws.OnMessage += (byte[] data) =>
            {
                string msg = System.Text.Encoding.UTF8.GetString(data);
                Enqueue(() => HandleMessage(msg));
            };
            ws.OnClose += (code) =>
            {
                connected = false;
                Debug.Log($"[WS] Closed: {code}");
            };
            ws.OnError += (err) => Debug.LogError($"[WS] Error: {err}");

            await ws.Connect();
        }
        catch (Exception e)
        {
            Debug.LogError($"[WS] Connection error: {e.Message}");
        }
    }

    void HandleMessage(string json)
    {
        try
        {
            var data = JsonUtility.FromJson<TwinState>(json);
            currentDamage = data.damage;
            currentSpeed = data.speed;
            currentState = data.led_state;
            currentConfidence = data.confidence;
            maintenanceAlert = data.maintenance_alert;

            if (data.stress_field != null && data.stress_field.Length > 0)
                stressField = data.stress_field;
            if (data.deformation_field != null && data.deformation_field.Length > 0)
                deformationField = data.deformation_field;

            Enqueue(UpdateUI);
            Enqueue(() => UpdateWingVisualization(data));
        }
        catch (Exception ex)
        {
            Debug.LogError($"[WS] Parse error: {ex.Message}");
        }
    }

    void UpdateUI()
    {
        if (damageSlider != null) damageSlider.value = currentDamage;
        if (damageLabel != null) damageLabel.text = $"Damage: {currentDamage * 100:F1}%";
        if (speedLabel != null) speedLabel.text = $"Vmax: {currentSpeed}%";
        if (confidenceLabel != null) confidenceLabel.text = $"Confidence: {currentConfidence:F1}%";
        if (alertLabel != null)
        {
            alertLabel.gameObject.SetActive(maintenanceAlert);
            if (maintenanceAlert) alertLabel.text = "MAINTENANCE REQUIRED";
        }

        if (ledImage != null)
        {
            ledFlashTimer += Time.deltaTime;
            if (currentState == "red" && ledFlashTimer > 0.4f)
            {
                ledFlash = !ledFlash;
                ledFlashTimer = 0f;
                ledImage.color = ledFlash ? redColor : Color.black;
            }
            else if (ledFlashTimer > 0.4f)
            {
                ledFlash = false;
                ledFlashTimer = 0f;
                ledImage.color = currentState switch
                {
                    "green" => greenColor,
                    "yellow" => yellowColor,
                    _ => redColor,
                };
            }
        }
    }

    void UpdateWingVisualization(TwinState data)
    {
        if (wingRenderer == null || stressGradient == null) return;

        float t = Mathf.Clamp01(currentDamage);
        Color stressColor = stressGradient.Evaluate(t);
        wingRenderer.material.color = stressColor;

        if (currentState == "red")
        {
            wingRenderer.material.EnableKeyword("_EMISSION");
            wingRenderer.material.SetColor("_EmissionColor", redColor * 2f);
        }
        else
        {
            wingRenderer.material.DisableKeyword("_EMISSION");
            float em = Mathf.Lerp(0.3f, 0.0f, t);
            wingRenderer.material.SetColor("_EmissionColor", new Color(em, em, em));
        }
    }

    void Enqueue(Action a) => mainThreadQueue.Enqueue(a);

    void LateUpdate()
    {
        while (mainThreadQueue.Count > 0)
            mainThreadQueue.Dequeue()?.Invoke();

#if !UNITY_WEBGL || UNITY_EDITOR
        if (ws != null) ws.DispatchMessageQueue();
#endif
    }

    async void OnDestroy()
    {
        if (ws != null) await ws.Close();
    }

    void OnGUI()
    {
        GUILayout.BeginArea(new Rect(10, 10, 360, 260));
        GUI.skin.label.fontSize = 16;
        GUILayout.Label($"WebSocket: {(connected ? "CONNECTED" : "DISCONNECTED")}");
        GUILayout.Label($"Damage:      {currentDamage * 100:F1}%");
        GUILayout.Label($"Vmax:        {currentSpeed}%");
        GUILayout.Label($"Confidence:  {currentConfidence:F1}%");
        GUILayout.Label($"LED State:   {currentState.ToUpper()}");
        GUILayout.Label($"Maintenance: {(maintenanceAlert ? "ACTIVE" : "none")}");
        if (stressField.Length > 0)
            GUILayout.Label($"Stress nodes: {stressField.Length}");
        if (deformationField.Length > 0)
            GUILayout.Label($"Deform nodes: {deformationField.Length}");
        GUILayout.Space(10);
        GUILayout.Label("SPACE = reconnect  |  ESC = disconnect");
        GUILayout.EndArea();

        if (!connected && GUI.Button(new Rect(10, Screen.height - 40, 150, 30), "Reconnect"))
            _ = ConnectAsync();
    }

    void Update()
    {
        if (!connected && Input.GetKeyDown(KeyCode.Space))
            _ = ConnectAsync();
        if (Input.GetKeyDown(KeyCode.Escape) && ws != null)
            _ = ws.Close();
    }

    [Serializable]
    public class TwinState
    {
        public float strain;
        public List<float> forces;
        public List<float> stress_field;
        public List<float> deformation_field;
        public float damage;
        public float confidence;
        public int speed;
        public string led_state;
        public bool maintenance_alert;
    }
}
