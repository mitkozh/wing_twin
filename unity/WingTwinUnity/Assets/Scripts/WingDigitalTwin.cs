/*
 * Wing Digital Twin - Unity WebSocket Client
 * Receives {strain, forces, stress_field, deformation_field, damage, confidence, speed, led_state, maintenance_alert}
 * from Python WebSocket via force-reconstruction pipeline.
 */

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using NativeWebSocket;
using Newtonsoft.Json;

public class WingDigitalTwin : MonoBehaviour
{
    [Header("Connection")]
    [SerializeField] private string serverUrl = "ws://localhost:8765";
    [SerializeField] private float reconnectDelay = 2f;
    [SerializeField] private float maxReconnectDelay = 30f;
    [SerializeField] private float heartbeatInterval = 10f;

    [Header("HUD")]
    [SerializeField] private Slider damageSlider;
    [SerializeField] private Text damageLabel;
    [SerializeField] private Text speedLabel;
    [SerializeField] private Text confidenceLabel;
    [SerializeField] private Image ledImage;
    [SerializeField] private Text alertLabel;
    [SerializeField] private Text connectionLabel;

    [Header("Wing Visualization")]
    [SerializeField] private Renderer wingRenderer;
    [SerializeField] private Gradient stressGradient;
    [SerializeField] private bool usePerVertexHeatmap = true;

    [Header("LED Colors")]
    [SerializeField] private Color greenColor = new Color(0.1f, 1.0f, 0.1f);
    [SerializeField] private Color yellowColor = new Color(1.0f, 0.9f, 0.1f);
    [SerializeField] private Color redColor = new Color(1.0f, 0.1f, 0.1f);

    private WebSocket ws;
    private bool connected = false;
    private float currentReconnectDelay;
    private float lastHeartbeatTime;
    private float lastMessageTime;
    private bool reconnectScheduled = false;

    private float currentDamage = 0f;
    private int currentSpeed = 100;
    private string currentState = "green";
    private float currentConfidence = 100f;
    private bool maintenanceAlert = false;
    private float[] stressField = Array.Empty<float>();
    private float[] deformationField = Array.Empty<float>();
    private float ledFlashTimer = 0f;
    private bool ledFlash = false;

    private Mesh mesh;
    private Color[] vertexColors;
    private float[] meshStressValues;
    private System.Collections.Generic.Dictionary<string, System.Action<string>> pendingCommands =
        new System.Collections.Generic.Dictionary<string, System.Action<string>>();

    private readonly System.Collections.Generic.Queue<Action> mainThreadQueue =
        new System.Collections.Generic.Queue<Action>();

    async void Start()
    {
        string meshPath = System.IO.Path.Combine(
            Application.streamingAssetsPath, "FinalMesh_surface.json");
        LoadMeshFromJson(meshPath);

        currentReconnectDelay = reconnectDelay;
        await ConnectAsync();
    }

    async Task ConnectAsync()
    {
        try
        {
            ws = new WebSocket(serverUrl);
            ws.OnOpen += () =>
            {
                connected = true;
                currentReconnectDelay = reconnectDelay;
                lastHeartbeatTime = Time.time;
                Debug.Log("[WS] Connected");
            };
            ws.OnMessage += (byte[] data) =>
            {
                lastMessageTime = Time.time;
                string msg = System.Text.Encoding.UTF8.GetString(data);
                Enqueue(() => HandleMessage(msg));
            };
            ws.OnClose += (code) =>
            {
                connected = false;
                Debug.Log($"[WS] Closed: {code}");
                ScheduleReconnect();
            };
            ws.OnError += (err) =>
            {
                Debug.LogError($"[WS] Error: {err}");
                connected = false;
                ScheduleReconnect();
            };

            await ws.Connect();
        }
        catch (Exception e)
        {
            Debug.LogError($"[WS] Connection error: {e.Message}");
            ScheduleReconnect();
        }
    }

    private async void ScheduleReconnect()
    {
        if (reconnectScheduled) return;
        reconnectScheduled = true;

        Debug.Log($"[WS] Scheduling reconnect in {currentReconnectDelay}s...");
        await Task.Delay(TimeSpan.FromSeconds(currentReconnectDelay));
        reconnectScheduled = false;

        await ConnectAsync();
        currentReconnectDelay = Mathf.Min(currentReconnectDelay * 1.5f, maxReconnectDelay);
    }

    private void SendHeartbeat()
    {
        if (ws != null && ws.State == WebSocketState.Open)
        {
            ws.SendText("{\"cmd\":\"ping\"}");
        }
    }

    void HandleMessage(string json)
    {
        try
        {
            if (json.Contains("\"cmd\":"))
            {
                var cmdResponse = JsonConvert.DeserializeObject<CommandResponse>(json);
                if (cmdResponse.cmd == "status")
                {
                    var status = JsonConvert.DeserializeObject<StatusResponse>(json);
                    currentDamage = status.damage;
                    currentSpeed = status.speed;
                    currentState = status.led_state;
                    currentConfidence = status.confidence;
                    Enqueue(UpdateUI);
                }
                else if (cmdResponse.cmd == "pong")
                {
                    Debug.Log("[WS] Heartbeat received");
                }
                return;
            }

            var data = JsonConvert.DeserializeObject<TwinState>(json);
            if (data == null) return;

            currentDamage = data.damage;
            currentSpeed = data.speed;
            currentState = data.led_state;
            currentConfidence = data.confidence;
            maintenanceAlert = data.maintenance_alert;

            if (data.stress_field != null && data.stress_field.Count > 0)
                stressField = data.stress_field.ToArray();
            if (data.deformation_field != null && data.deformation_field.Count > 0)
                deformationField = data.deformation_field.ToArray();

            Enqueue(UpdateUI);
            Enqueue(() => UpdateWingVisualization(data));
        }
        catch (Exception ex)
        {
            Debug.LogError($"[WS] Parse error: {ex.Message}");
        }
    }

    [Serializable]
    public class CommandResponse
    {
        public string cmd;
    }

    [Serializable]
    public class StatusResponse
    {
        public string cmd;
        public bool running;
        public float damage;
        public float confidence;
        public string led_state;
        public int speed;
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

        if (usePerVertexHeatmap && mesh != null && stressField.Length > 0)
        {
            UpdateHeatmap();
        }
        else
        {
            float t = Mathf.Clamp01(currentDamage);
            Color stressColor = stressGradient.Evaluate(t);
            wingRenderer.material.color = stressColor;
        }

        if (currentState == "red")
        {
            wingRenderer.material.EnableKeyword("_EMISSION");
            wingRenderer.material.SetColor("_EmissionColor", redColor * 2f);
        }
        else
        {
            wingRenderer.material.DisableKeyword("_EMISSION");
            float em = Mathf.Lerp(0.3f, 0.0f, currentDamage);
            wingRenderer.material.SetColor("_EmissionColor", new Color(em, em, em));
        }
    }

    void UpdateHeatmap()
    {
        if (mesh == null || stressField.Length == 0) return;

        int vertexCount = mesh.vertexCount;
        if (stressField.Length != vertexCount)
        {
            Debug.LogWarning($"Stress field length ({stressField.Length}) != vertex count ({vertexCount})");
            return;
        }

        if (vertexColors == null || vertexColors.Length != vertexCount)
            vertexColors = new Color[vertexCount];

        float minS = stressField.Min();
        float maxS = stressField.Max();
        float range = maxS - minS;

        if (range < 0.001f) range = 1f;

        for (int i = 0; i < vertexCount; i++)
        {
            float t = Mathf.InverseLerp(minS, maxS, stressField[i]);
            vertexColors[i] = stressGradient.Evaluate(t);
        }

        mesh.colors = vertexColors;
        mesh.MarkDynamic();
    }

    public void LoadMeshFromJson(string jsonPath)
    {
        if (!System.IO.File.Exists(jsonPath))
        {
            Debug.LogError($"Mesh file not found: {jsonPath}");
            return;
        }

        string json = System.IO.File.ReadAllText(jsonPath);
        MeshData data = JsonConvert.DeserializeObject<MeshData>(json);

        if (data?.vertices == null || data?.triangles == null)
        {
            Debug.LogError("Failed to load mesh: parsed data is null.");
            return;
        }

        mesh = new Mesh();
        mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;

        Vector3[] vertices = data.vertices.Select(v => new Vector3(v[0], v[2], v[1])).ToArray();
        mesh.vertices = vertices;

        int[] triangles = data.triangles.SelectMany(t => t).ToArray();
        mesh.triangles = triangles;

        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        GetComponent<MeshFilter>().mesh = mesh;
        meshStressValues = new float[vertices.Length];

        Debug.Log($"Loaded mesh: {vertices.Length} vertices, {triangles.Length / 3} triangles");
    }

    [Serializable]
    public class MeshData
    {
        public List<List<float>> vertices;
        public List<List<int>> triangles;
    }

    void SendCommand(string cmd, System.Collections.Generic.Dictionary<string, object> args = null, System.Action<string> callback = null)
    {
        if (ws == null || ws.State != WebSocketState.Open) return;

        var payload = new System.Collections.Generic.Dictionary<string, object> { { "cmd", cmd } };
        if (args != null)
        {
            foreach (var kv in args) payload[kv.Key] = kv.Value;
        }

        string json = JsonUtility.ToJson(payload);
        ws.SendText(json);

        if (callback != null)
        {
            string requestId = cmd + "_" + System.DateTime.Now.Ticks;
            pendingCommands[requestId] = callback;
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
        float msgAge = Time.time - lastMessageTime;

        GUILayout.BeginArea(new Rect(10, 10, 380, 300));
        GUI.skin.label.fontSize = 16;
        GUILayout.Label($"WebSocket: {(connected ? "CONNECTED" : "DISCONNECTED")}");
        if (connected)
            GUILayout.Label($"Last msg:   {(msgAge * 1000):F0}ms ago");
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
        GUILayout.Label($"Reconnect delay: {currentReconnectDelay:F1}s");
        GUILayout.EndArea();

        if (!connected && GUI.Button(new Rect(10, Screen.height - 40, 150, 30), "Reconnect"))
            _ = ConnectAsync();
    }

    void Update()
    {
        // Connection health monitoring
        if (connected)
        {
            float timeSinceLastMsg = Time.time - lastMessageTime;
            if (timeSinceLastMsg > heartbeatInterval * 2)
            {
                Debug.LogWarning("[WS] No messages received, reconnecting...");
                connected = false;
                ScheduleReconnect();
            }
            else if (Time.time - lastHeartbeatTime > heartbeatInterval)
            {
                SendHeartbeat();
                lastHeartbeatTime = Time.time;
            }
        }

        if (!connected && Input.GetKeyDown(KeyCode.Space))
            _ = ConnectAsync();
        if (Input.GetKeyDown(KeyCode.Escape) && ws != null)
            _ = ws.Close();

        if (connected)
        {
            if (Input.GetKeyDown(KeyCode.P))
            {
                SendCommand("pause");
            }
            if (Input.GetKeyDown(KeyCode.R))
            {
                SendCommand("reset", new System.Collections.Generic.Dictionary<string, object> { { "target", "damage" } });
            }
            if (Input.GetKeyDown(KeyCode.S))
            {
                SendCommand("status");
            }
            if (Input.GetKeyDown(KeyCode.F))
            {
                ApplyForce(10.0f);
            }
            if (Input.GetKeyDown(KeyCode.G))
            {
                ApplyForce(-10.0f);
            }
        }

        // Update connection label
        if (connectionLabel != null)
        {
            float latency = (Time.time - lastMessageTime) * 1000;
            connectionLabel.text = connected ? $"CONNECTED ({latency:F0}ms)" : "DISCONNECTED";
            connectionLabel.color = connected ? Color.green : Color.red;
        }
    }

    public void ApplyForce(float forceNewtons)
    {
        SendCommand("apply_force", new System.Collections.Generic.Dictionary<string, object> { { "force", forceNewtons } });
        Debug.Log($"[CMD] Applying force: {forceNewtons}N");
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
