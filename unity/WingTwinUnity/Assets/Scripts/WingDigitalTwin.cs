/*
 * Wing Digital Twin - Unity WebSocket Client
 * Receives {strain, forces, stress_field, deformation_field, damage, confidence, speed, led_state, maintenance_alert}
 * from Python WebSocket via force-reconstruction pipeline.
 */

using NativeWebSocket;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class WingDigitalTwin : MonoBehaviour
{
    [Header("Connection")]
    [SerializeField] private string serverUrl = "ws://localhost:8765";
    [SerializeField] private float reconnectDelay = 2f;
    [SerializeField] private float maxReconnectDelay = 10f;
    [SerializeField] private float heartbeatInterval = 10f;

    [Header("HUD")]
    [SerializeField] private Slider damageSlider;
    [SerializeField] private TextMeshProUGUI damageLabel;
    [SerializeField] private Slider avgDamageSlider;
    [SerializeField] private TextMeshProUGUI avgDamageLabel;
    [SerializeField] private TextMeshProUGUI speedLabel;
    [SerializeField] private TextMeshProUGUI confidenceLabel;
    [SerializeField] private TextMeshProUGUI alertLabel;
    [SerializeField] private TextMeshProUGUI connectionLabel;
    [SerializeField] private Toggle heatmapModeToggle;
    [SerializeField] private Text heatmapToggleLabel;
    [SerializeField] private Image stressBar;
    public int stressBarHeight = 256;
    public int stressBarWidth = 16;

    [Header("Wing Visualization")]
    [SerializeField] private Renderer wingRenderer;
    [SerializeField] private Gradient stressGradient;
    [SerializeField] private bool usePerVertexHeatmap = true;

    [Header("PlaneVisualization")]
    [SerializeField] GameObject rotationalPivot;
    [SerializeField] Slider planeAngleSlider;
    [SerializeField] Slider stepsSlider;
    [SerializeField] Slider speedSlider;
    [SerializeField] TextMeshProUGUI angleSliderLabel;
    [SerializeField] TextMeshProUGUI stepsSliderLabel;
    [SerializeField] TextMeshProUGUI speedSliderLabel;
    [SerializeField] GameObject planeScene;
    [SerializeField] TextMeshProUGUI planeCurrentSpeedLabel;
    [SerializeField] TextMeshProUGUI planeTargetSpeedLabel;
    [SerializeField] TextMeshProUGUI planeTargetAngleLabel;
    [SerializeField] TextMeshProUGUI planeCurrentAngleLabel;
    [SerializeField] List<ParticleSystem> windParticles = new List<ParticleSystem>();
    [SerializeField] float commonPlaneSpeed = 120f;
    [SerializeField] float windExaggeration = 1f;
    [SerializeField] float angleAdjustmentTime = 10;
    [SerializeField] float speedAdjustmentTime = 10;

    const float MAX_ANGLE_DEGREES = 15f;
    const float MAX_SPEED_KMH = 200f;
    const float MAX_STEPPER_STEPS = 2720f;

    [Header("LED Colors")]
    [SerializeField] private Color greenColor = new Color(0.1f, 1.0f, 0.1f);
    [SerializeField] private Color yellowColor = new Color(1.0f, 0.9f, 0.1f);
    [SerializeField] private Color redColor = new Color(1.0f, 0.1f, 0.1f);

    [Header("Help Panel")]
    [SerializeField] GameObject helpPanel;

    [Header("Simulation Parameters")]
    [SerializeField] float scaling = 1f;

    [Header("Canvas Elements")]
    [SerializeField] List<ViewGroup> UIViewGroups = new List<ViewGroup>();

    private float currentPlaneAngle = 0;
    private float currentPlaneSpeed = 80f; 
    private float angleElapsedTime = 0f;
    private float speedElapsedTime = 0f;
    private Image fillImage;

    private WebSocket ws;
    private bool connected = false;
    private float currentReconnectDelay;
    private float lastHeartbeatTime = 0f;
    private float lastMessageTime = 0f;
    private bool reconnectScheduled = false;

    private float newAngleOfAttack = 0f;
    private float previousAngleOfAttack = 0f;
    private float newPlaneSpeed = 0f;
    private float previousPlaneSpeed = 80f;
    private float currentDamage = 0f;
    private float currentAvgDamage = 0f;
    private int currentSpeed = 100;
    private string currentState = "green";
    private float currentConfidence = 100f;
    private bool maintenanceAlert = false;
    private float[] stressField = Array.Empty<float>();
    private float[] deformationField = Array.Empty<float>();
    private float[] nodeDamages = Array.Empty<float>();
    private bool showDamageHeatmap = false;
    private bool suppressSliderCallback = false;

    public RectTransform stressBarRect;
    public TMP_Text labelPrefab;
    public Transform labelParent;

    private readonly List<TMP_Text> stressLabels = new();

    private Mesh mesh;
    private Vector3[] originalVertices;
    private Vector3[] deformedVertices;
    private float stressMin;
    private float stressMax;

    private Color[] vertexColors;
    private float[] meshStressValues;
    private System.Collections.Generic.Dictionary<string, System.Action<string>> pendingCommands =
        new System.Collections.Generic.Dictionary<string, System.Action<string>>();
    public float correctionValue;
    private readonly System.Collections.Generic.Queue<Action> mainThreadQueue =
        new System.Collections.Generic.Queue<Action>();

    async void Start()
    {   
        CreateStressBar();
        BuildStressLegendLabels();
        string meshPath = System.IO.Path.Combine(
            Application.streamingAssetsPath, "FinalMesh_surface.json");
        LoadMeshFromJson(meshPath);

        currentReconnectDelay = reconnectDelay;
        lastMessageTime = Time.time;
        lastHeartbeatTime = Time.time;

        if (heatmapModeToggle != null)
        {
            heatmapModeToggle.onValueChanged.AddListener(OnHeatmapModeChanged);
            heatmapModeToggle.SetIsOnWithoutNotify(false);
        }
        UpdateHeatmapToggleLabel(false);

        fillImage = planeAngleSlider.fillRect.GetComponent<Image>();
        planeAngleSlider.onValueChanged.AddListener(OnAngleSliderChanged);
        if (speedSlider != null)
            speedSlider.onValueChanged.AddListener(OnSpeedSliderChanged);

        planeAngleSlider.minValue = -MAX_ANGLE_DEGREES;
        planeAngleSlider.maxValue = MAX_ANGLE_DEGREES;
        if (stepsSlider != null)
        {
            stepsSlider.minValue = 0f;
            stepsSlider.maxValue = MAX_STEPPER_STEPS;
        }
        if (speedSlider != null)
        {
            speedSlider.minValue = 0f;
            speedSlider.maxValue = MAX_SPEED_KMH;
        }

        await ConnectAsync();
    }
    
    private void UpdatePlaneSpeed()
    {
        speedElapsedTime += Time.deltaTime;

        float t = Mathf.Clamp01(speedElapsedTime / speedAdjustmentTime);
        currentPlaneSpeed = Mathf.Lerp(previousPlaneSpeed, newPlaneSpeed, t);

        planeCurrentSpeedLabel.text = $"Current Plane Speed: {currentPlaneSpeed}";
        planeTargetSpeedLabel.text = $"Target Plane Speed: {newPlaneSpeed}";

        foreach (ParticleSystem ps in windParticles)
        {
            float change = currentPlaneSpeed / commonPlaneSpeed;
            ParticleSystem.MainModule main = ps.main;
            float speed = change * windExaggeration;
            main.startSpeed = speed;
            main.startLifetime = 10f / speed;
        }
    }
    private void UpdatePlaneAngle()
    {
        angleElapsedTime += Time.deltaTime;

        float t = Mathf.Clamp01(angleElapsedTime / angleAdjustmentTime);
        currentPlaneAngle = Mathf.Lerp(previousAngleOfAttack, newAngleOfAttack, t);

        Vector3 current = rotationalPivot.transform.localEulerAngles;
        rotationalPivot.transform.localRotation = Quaternion.Euler(currentPlaneAngle, current.y, current.z);

        float normalised = Mathf.InverseLerp(planeAngleSlider.minValue, planeAngleSlider.maxValue, currentPlaneAngle);
        fillImage.fillAmount = normalised;

        planeCurrentAngleLabel.text = $"Current Plane Angle: {currentPlaneAngle}";
        planeTargetAngleLabel.text = $"Target Plane Angle: {newAngleOfAttack}";
    }

    public void SwitchViewButton(int camera)
    {
        if (camera > UIViewGroups.Count)
        {
            return;
        }

        SwitchView(camera);
    }

    private void SwitchView(int camera)
    {
        int index = camera - 1;
         bool planeSceneNeeded = false;

        for (int i = 0; i < UIViewGroups.Count; i++)
        {
            GameObject uiGroup = UIViewGroups[i].uiViewGroup;
            GameObject viewCamera = UIViewGroups[i].viewCamera;
            GameObject worldUIGroup = UIViewGroups[i].worldUIViewGroup;
            

            bool active = i == index;

            if (uiGroup != null)
                uiGroup.SetActive(active);

            if (worldUIGroup != null)
                worldUIGroup.SetActive(active);

            if (viewCamera != null)
                viewCamera.SetActive(active);

            if (active && UIViewGroups[i].needPlaneScene)
            {
                planeSceneNeeded = true;
            }
        }

        planeScene.SetActive(planeSceneNeeded);
    }

    void CreateStressBar()
    {
        Texture2D tex = MakeGradientTexture(stressGradient);

        stressBar.sprite = Sprite.Create(
            tex,
            new Rect(0, 0, tex.width, tex.height),
            new Vector2(0.5f, 0.5f)
        );

        stressBar.type = Image.Type.Simple;
        stressBar.preserveAspect = false;

        RectTransform rt = stressBar.GetComponent<RectTransform>();
        rt.sizeDelta = new Vector2(stressBarWidth, stressBarHeight);
    }

    Texture2D MakeGradientTexture(Gradient gradient)
    {
        Texture2D tex = new Texture2D(stressBarWidth, stressBarHeight);

        for (int y = 0; y < stressBarHeight; y++)
        {
            float t = y / (float)(stressBarHeight - 1);
            Color c = gradient.Evaluate(t);

            for (int x = 0; x < stressBarWidth; x++)
                tex.SetPixel(x, y, c);
        }

        tex.Apply();
        return tex;
    }

    void BuildStressLegendLabels()
    {
        float h = stressBarRect.rect.height - correctionValue;
        float halfH = h * 0.5f;

        int labelCount = stressGradient.colorKeys.Length + 1;

        for (int i = 0; i < labelCount; i++)
        {
            float t = i / (float)(labelCount - 1);

            TMP_Text label = Instantiate(labelPrefab, stressBarRect);
            stressLabels.Add(label);

            RectTransform rt = label.GetComponent<RectTransform>();

            rt.anchorMin = new Vector2(0.5f, 0.5f);
            rt.anchorMax = new Vector2(0.5f, 0.5f);
            rt.pivot = new Vector2(1f, 0.5f);

            float y = Mathf.Lerp(-halfH, halfH, t);
            float x = -10f;

            rt.localPosition = new Vector3(x, y, 0f);
        }
    }

    void UpdateStressLegendValues()
    {
        if (stressLabels == null || stressLabels.Count == 0)
            return;

        int labelCount = stressLabels.Count;

        for (int i = 0; i < labelCount; i++)
        {
            float t = i / (float)(labelCount - 1);
            float value = Mathf.Lerp(stressMin, stressMax, t);

            string suffix = "";

            if (i == labelCount - 1)
                suffix = " Max";
            else if (i == 0)
                suffix = " Min";

            stressLabels[i].text = $"{value:E3}{suffix}";
        }
    }

    async Task ConnectAsync()
    {
        if (connected) return;

        try
        {
            if (ws != null)
            {
                try { _ = ws.Close(); } catch { }
            }

            ws = new WebSocket(serverUrl);
            ws.OnOpen += () =>
            {
                connected = true;
                reconnectScheduled = false;
                currentReconnectDelay = reconnectDelay;
                lastHeartbeatTime = Time.time;
                lastMessageTime = Time.time;
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
                if (!reconnectScheduled)
                    ScheduleReconnect();
            };
            ws.OnError += (err) =>
            {
                Debug.LogError($"[WS] Error: {err}");
                connected = false;
                if (!reconnectScheduled)
                    ScheduleReconnect();
            };

            await ws.Connect();
        }
        catch (Exception e)
        {
            Debug.LogError($"[WS] Connection error: {e.Message}");
            if (!reconnectScheduled)
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
            currentAvgDamage = data.avg_damage;
            currentSpeed = data.speed;
            currentState = data.led_state;
            currentConfidence = data.confidence;
            maintenanceAlert = data.maintenance_alert;
            stressMin = data.stress_min;
            stressMax = data.stress_max;


            float incomingPlaneSpeed = data.new_speed;
            float incomingAngle = data.new_angle_of_attack;

            if (!Mathf.Approximately(incomingPlaneSpeed, newPlaneSpeed))
            {
                previousPlaneSpeed = currentPlaneSpeed;
                newPlaneSpeed = incomingPlaneSpeed;
                speedElapsedTime = 0;
            }

            if (!Mathf.Approximately(incomingAngle, newAngleOfAttack))
            {
                previousAngleOfAttack = currentPlaneAngle;
                newAngleOfAttack = incomingAngle;
                angleElapsedTime = 0f;
            }

            suppressSliderCallback = true;
            planeAngleSlider.value = newAngleOfAttack;
            if (stepsSlider != null)
            {
                stepsSlider.value = data.stepper_position;
                if (stepsSliderLabel != null)
                    stepsSliderLabel.text = $"Steps: {data.stepper_position}";
            }
            if (speedSlider != null)
                speedSlider.value = newPlaneSpeed;
            suppressSliderCallback = false;

            if (data.stress_field != null && data.stress_field.Count > 0)
                stressField = data.stress_field.ToArray();
            if (data.deformation_field != null && data.deformation_field.Count > 0)
                deformationField = data.deformation_field.ToArray();
            if (data.node_damages != null && data.node_damages.Count > 0)
                nodeDamages = data.node_damages.ToArray();

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
        UpdateDamageSlider(damageSlider, damageLabel, currentDamage, "Max Damage");
        UpdateDamageSlider(avgDamageSlider, avgDamageLabel, currentAvgDamage, "Avg Damage");
        
        if (speedLabel != null) speedLabel.text = $"Vmax: {currentSpeed}%";
        if (confidenceLabel != null) confidenceLabel.text = $"Confidence: {currentConfidence:F1}%";
        if (alertLabel != null)
        {
            alertLabel.gameObject.SetActive(maintenanceAlert);
            if (maintenanceAlert) alertLabel.text = "MAINTENANCE REQUIRED";
        }

        if (stepsSliderLabel != null && stepsSlider != null)
            stepsSliderLabel.text = $"Steps: {(int)stepsSlider.value}";
    }

    void UpdateDamageSlider(Slider slider, TextMeshProUGUI label, float value, string title)
    {
        if (slider != null)
        {
            slider.value = value;
            Color sliderColor = value switch
            {
                >= 0.8f => redColor,
                >= 0.3f => yellowColor,
                _ => greenColor,
            };
            slider.fillRect.GetComponent<Image>().color = sliderColor;
        }
        if (label != null)
            label.text = $"{title}: {value * 100:F1}%";
    }

    void UpdateWingVisualization(TwinState data)
    {
        if (wingRenderer == null || stressGradient == null) return;

        if (usePerVertexHeatmap && mesh != null)
        {
            if (showDamageHeatmap && nodeDamages.Length > 0)
            {
                UpdateDamageHeatmap();
            }
            else if (stressField.Length > 0)
            {
                UpdateHeatmap();
            }
        }
        else
        {
            float t = Mathf.Clamp01(currentDamage);
            Color stressColor = stressGradient.Evaluate(t);
            wingRenderer.material.color = stressColor;
        }

        if (deformationField.Length > 0)
        {
            UpdateDeformation();
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

        UpdateStressLegendValues();
    }

    void UpdateDeformation()
    {
        if (mesh == null || deformationField.Length == 0) return;

        if (deformationField.Length != originalVertices.Length)
        {
            Debug.LogWarning($"Deformation field length ({deformationField.Length}) != vertex count ({originalVertices.Length})");
            return;
        }

        for (int i = 0; i < originalVertices.Length; i++)
        {
            float updatedY = originalVertices[i].y + deformationField[i] * scaling;

            deformedVertices[i] = new Vector3(originalVertices[i].x,
                updatedY,
                originalVertices[i].z
                );
        }

        mesh.vertices = deformedVertices;
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

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

        float minS = 0f;
        float maxS = 1000000f;

        for (int i = 0; i < vertexCount; i++)
        {
            float absStress = Mathf.Abs(stressField[i]);
            float t = Mathf.Clamp01(absStress / maxS);
            vertexColors[i] = stressGradient.Evaluate(t);
        }

        mesh.colors = vertexColors;
        mesh.MarkDynamic();
    }

    void UpdateDamageHeatmap()
    {
        if (mesh == null || nodeDamages.Length == 0) return;

        int vertexCount = mesh.vertexCount;
        if (nodeDamages.Length != vertexCount)
        {
            Debug.LogWarning($"Node damages length ({nodeDamages.Length}) != vertex count ({vertexCount})");
            return;
        }

        if (vertexColors == null || vertexColors.Length != vertexCount)
            vertexColors = new Color[vertexCount];

        for (int i = 0; i < vertexCount; i++)
        {
            float t = Mathf.Clamp01(nodeDamages[i]);
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

        originalVertices = data.vertices.Select(v => new Vector3(v[0], v[1], v[2])).ToArray();
        mesh.vertices = originalVertices;

        deformedVertices = new Vector3[originalVertices.Length];

        int[] triangles = data.triangles.SelectMany(t => t).ToArray();
        mesh.triangles = triangles;

        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        wingRenderer.GetComponent<MeshFilter>().mesh = mesh;
        meshStressValues = new float[originalVertices.Length];

        Debug.Log($"Loaded mesh: {originalVertices.Length} vertices, {triangles.Length / 3} triangles");
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

        string json = JsonConvert.SerializeObject(payload);
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
                UI_Pause();
            }
            if (Input.GetKeyDown(KeyCode.R))
            {
                UI_Reset();
            }
            if (Input.GetKeyDown(KeyCode.S))
            {
                UI_Status();
            }
            if (Input.GetKeyDown(KeyCode.F))
            {
                SendFlightState(planeAngleSlider.value, speedSlider != null ? speedSlider.value : currentPlaneSpeed);
            }
            if (Input.GetKeyDown(KeyCode.H))
            {
                ToggleHelp();
            }
            if (Input.GetKeyDown(KeyCode.M))
            {
                ToggleHeatmapMode();
            }
        }

        // Update connection label
        if (connectionLabel != null)
        {
            float latency = (Time.time - lastMessageTime) * 1000;
            connectionLabel.text = connected ? $"CONNECTED" : "DISCONNECTED";
            connectionLabel.color = connected ? Color.green : Color.red;
        }

        UpdatePlaneAngle();
        UpdatePlaneSpeed();
    }

    public void ToggleHelp()
    {
        if (helpPanel != null)
            helpPanel.SetActive(!helpPanel.activeSelf);
    }

    public void ToggleHeatmapMode()
    {
        showDamageHeatmap = !showDamageHeatmap;
        if (heatmapModeToggle != null)
            heatmapModeToggle.SetIsOnWithoutNotify(showDamageHeatmap);
        UpdateHeatmapToggleLabel(showDamageHeatmap);
        SendCommand("set_heatmap_mode", new Dictionary<string, object> { { "mode", showDamageHeatmap ? "damage" : "stress" } });
        Debug.Log($"[HEATMAP] Mode: {(showDamageHeatmap ? "DAMAGE" : "STRESS")}");
    }

    void OnHeatmapModeChanged(bool isOn)
    {
        showDamageHeatmap = isOn;
        UpdateHeatmapToggleLabel(isOn);
        SendCommand("set_heatmap_mode", new Dictionary<string, object> { { "mode", isOn ? "damage" : "stress" } });
        Debug.Log($"[HEATMAP] Mode: {(showDamageHeatmap ? "DAMAGE" : "STRESS")}");
    }

    void UpdateHeatmapToggleLabel(bool isDamageMode)
    {
        if (heatmapToggleLabel != null)
            heatmapToggleLabel.text = isDamageMode ? "Damage" : "Stress";
    }

    public void UI_Pause()  => SendCommand("pause");
    public void UI_Reset()  => SendCommand("reset",
        new Dictionary<string, object> { { "target", "damage" } });
    public void UI_Status() => SendCommand("status");

    void OnAngleSliderChanged(float angle)
    {
        if (suppressSliderCallback) return;
        suppressSliderCallback = true;

        UpdateSliderLabel(angleSliderLabel, $"Angle: {angle:F1}°");

        suppressSliderCallback = false;

        float speed = speedSlider != null ? speedSlider.value : currentPlaneSpeed;
        SendFlightState(angle, speed);
    }

    void OnSpeedSliderChanged(float speed)
    {
        if (suppressSliderCallback) return;

        UpdateSliderLabel(speedSliderLabel, $"Speed: {speed:F0} km/h");

        float angle = planeAngleSlider != null ? planeAngleSlider.value : 0f;
        SendFlightState(angle, speed);
    }

    void UpdateSliderLabel(TextMeshProUGUI label, string text)
    {
        if (label != null) label.text = text;
    }

    public void SendFlightState(float angle, float speed)
    {
        SendCommand("set_flight_state", new Dictionary<string, object> { { "angle", angle }, { "speed", speed } });
    }

    [Serializable]
    public class TwinState
    {
        public float strain;
        public List<float> forces;
        public List<float> stress_field;
        public List<float> deformation_field;
        public float damage;
        public float avg_damage;
        public List<float> node_damages;
        public float confidence;
        public int speed;
        public string led_state;
        public bool maintenance_alert;
        public float stress_min;
        public float stress_max;
        public float new_angle_of_attack;
        public float new_speed;
        public int stepper_position;
    }

    [Serializable]
    public class ViewGroup
    {
        public GameObject viewCamera;
        public GameObject uiViewGroup;
        public GameObject worldUIViewGroup;
        public bool needPlaneScene;
    }

}
