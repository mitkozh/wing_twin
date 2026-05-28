/*
 * Wing Digital Twin Unity WebSocket Client
 */
using NativeWebSocket;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using TMPro;
using UnityEngine;
using UnityEngine.InputSystem;
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
    [SerializeField] Slider allowedAngleSlider;
    [SerializeField] Slider allowedSpeedSlider;
    [SerializeField] TextMeshProUGUI angleSliderLabel;
    [SerializeField] TextMeshProUGUI stepsSliderLabel;
    [SerializeField] TextMeshProUGUI speedSliderLabel;
    [SerializeField] GameObject planeScene;
    [SerializeField] TextMeshProUGUI planeCurrentSpeedLabel;
    //[SerializeField] TextMeshProUGUI planeTargetSpeedLabel;
    //[SerializeField] TextMeshProUGUI planeTargetAngleLabel;
    [SerializeField] TextMeshProUGUI planeCurrentAngleLabel;
    [SerializeField] List<ParticleSystem> windParticles = new List<ParticleSystem>();
    [SerializeField] float commonPlaneSpeed = 40f;
    [SerializeField] float windExaggeration = 1f;
    [SerializeField] Color desiredColor = Color.black;
    [SerializeField] Color allowedColor = new Color(0.75f, 0.20f, 0.30f);

    float maxAngleDeg = 12f;
    float maxSpeedKmh = 80f;
    float maxStepperSteps = 2720f;

    [Header("LED Colors")]
    [SerializeField] private Color greenColor = new Color(0.1f, 1.0f, 0.1f);
    [SerializeField] private Color yellowColor = new Color(1.0f, 0.9f, 0.1f);
    [SerializeField] private Color redColor = new Color(1.0f, 0.1f, 0.1f);

    [Header("Help Panel")]
    [SerializeField] GameObject helpPanel;

    [Header("Simulation Parameters")]
    [SerializeField] float scaling = 1f;

    [Header("Charts")]
    [SerializeField] private ChartPanel chartPanel;

    [Header("Canvas Elements")]
    [SerializeField] List<ViewGroup> UIViewGroups = new List<ViewGroup>();

    private float currentPlaneAngle = 0;
    private float currentPlaneSpeed = 80f;

    private WebSocket ws;
    private bool connected = false;
    private float currentReconnectDelay;
    private float lastHeartbeatTime = 0f;
    private float lastMessageTime = 0f;
    private bool reconnectScheduled = false;

    private float targetAngleOfAttack = 0f;
    private float targetPlaneSpeed = 0f;
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
    private float yieldPointPa = 100_000_000f;

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

        if (chartPanel != null)
        {
            chartPanel.gameObject.SetActive(false);
        }

        currentReconnectDelay = reconnectDelay;
        lastMessageTime = Time.time;
        lastHeartbeatTime = Time.time;

        if (heatmapModeToggle != null)
        {
            heatmapModeToggle.onValueChanged.AddListener(OnHeatmapModeChanged);
            heatmapModeToggle.SetIsOnWithoutNotify(false);
        }
        UpdateHeatmapToggleLabel(false);

        planeAngleSlider.onValueChanged.AddListener(OnAngleSliderChanged);
        if (speedSlider != null)
            speedSlider.onValueChanged.AddListener(OnSpeedSliderChanged);

        planeAngleSlider.minValue = -maxAngleDeg;
        planeAngleSlider.maxValue = maxAngleDeg;

        allowedAngleSlider.minValue = -maxAngleDeg;
        allowedAngleSlider.maxValue = maxAngleDeg;

        if (stepsSlider != null)
        {
            stepsSlider.minValue = 0f;
            stepsSlider.maxValue = maxStepperSteps;
        }
        if (speedSlider != null)
        {
            speedSlider.minValue = 0f;
            speedSlider.maxValue = maxSpeedKmh;

            allowedSpeedSlider.minValue = 0;
            allowedSpeedSlider.maxValue = maxSpeedKmh;
        }

        await ConnectAsync();
    }
    
    private void UpdatePlaneSpeed()
    {
        planeCurrentSpeedLabel.text = $"Current Plane Speed: {currentPlaneSpeed:F1}";
        //planeTargetSpeedLabel.text = $"Allowed Plane Speed: {targetPlaneSpeed:F1}";

        //Debug.Log($"currentPlaneSpeed={currentPlaneSpeed}, common={commonPlaneSpeed}, exaggeration={windExaggeration}");
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
        rotationalPivot.transform.localRotation = Quaternion.Euler(currentPlaneAngle, 0, 0);

        planeCurrentAngleLabel.text = $"Current Plane Angle: {currentPlaneAngle:F1}";
        //planeTargetAngleLabel.text = $"Allowed Plane Angle: {targetAngleOfAttack:F1}";
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

    void UpdateLegendValues()
    {
        if (stressLabels == null || stressLabels.Count == 0)
            return;

        int labelCount = stressLabels.Count;

        if (showDamageHeatmap)
        {
            for (int i = 0; i < labelCount; i++)
            {
                float t = i / (float)(labelCount - 1);
                float value = Mathf.Lerp(0f, 1f, t);

                string suffix = "";
                if (i == labelCount - 1)
                    suffix = " Max";
                else if (i == 0)
                    suffix = " Min";

                stressLabels[i].text = $"{value:P0}{suffix}";
            }
        }
        else
        {
            for (int i = 0; i < labelCount; i++)
            {
                float t = i / (float)(labelCount - 1);
                float value = Mathf.Lerp(0f, yieldPointPa, t);

                string suffix = "";
                if (i == labelCount - 1)
                    suffix = " Max";
                else if (i == 0)
                    suffix = " Min";

                stressLabels[i].text = $"{value:E3}{suffix}";
            }
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

    void PushChartData(TwinState data)
    {
        if (chartPanel == null) return;

        chartPanel.PushStrain(data.strain);
        chartPanel.PushDamage(data.damage);
        chartPanel.PushStress(data.stress_max, data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa);

        if (data.cycles_binned != null && data.cycles_binned.Count > 0)
        {
            float[] ranges = data.cycles_binned.Select(c => c.range).ToArray();
            float[] counts = data.cycles_binned.Select(c => c.count).ToArray();
            chartPanel.SetRainflowBins(ranges, counts);
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
            yieldPointPa = data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa;
            if (data.max_angle_deg > 0) {
                maxAngleDeg = data.max_angle_deg;
                planeAngleSlider.minValue = -maxAngleDeg;
                planeAngleSlider.maxValue = maxAngleDeg;

                allowedAngleSlider.minValue = -maxAngleDeg;
                allowedAngleSlider.maxValue = maxAngleDeg;
            }
            if (data.max_speed_kmh > 0) {
                maxSpeedKmh = data.max_speed_kmh;
                speedSlider.maxValue = maxSpeedKmh;

                allowedSpeedSlider.maxValue = maxSpeedKmh;
            }
            if (data.max_stepper_steps > 0) {
                maxStepperSteps = data.max_stepper_steps;
                stepsSlider.maxValue = maxStepperSteps;
            }

            currentPlaneAngle = data.new_angle_of_attack;
            currentPlaneSpeed = data.new_speed;
            targetAngleOfAttack = data.target_angle_of_attack;
            targetPlaneSpeed = data.target_speed;

            string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
            string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

            if (stepsSliderLabel != null)
                stepsSliderLabel.text = $"Steps: {data.stepper_position}";
            if (angleSliderLabel != null)
                angleSliderLabel.text = $"<color={desiredHex}>Desired Angle: {planeAngleSlider.value:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}°</color>";
            if (speedSliderLabel != null)
                speedSliderLabel.text = $"<color={desiredHex}>Desired Speed: {speedSlider.value:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>";

            //suppressSliderCallback = true;
            if (stepsSlider != null)
                stepsSlider.value = data.stepper_position;
            if (allowedAngleSlider != null)
                allowedAngleSlider.value = targetAngleOfAttack;
            if (allowedSpeedSlider != null)
                allowedSpeedSlider.value = targetPlaneSpeed;
            //suppressSliderCallback = false;

            if (data.stress_field != null && data.stress_field.Count > 0)
                stressField = data.stress_field.ToArray();
            if (data.deformation_field != null && data.deformation_field.Count > 0)
                deformationField = data.deformation_field.ToArray();
            if (data.node_damages != null && data.node_damages.Count > 0)
                nodeDamages = data.node_damages.ToArray();

            Enqueue(UpdateUI);
            Enqueue(() => UpdateWingVisualization(data));
            Enqueue(() => PushChartData(data));
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

        UpdateLegendValues();
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

        // float minS = 0f;
        //float maxS = 1000000f;

        for (int i = 0; i < vertexCount; i++)
        {
            float absStress = Mathf.Abs(stressField[i]);
            float t = Mathf.Clamp01(absStress / yieldPointPa);
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

        if (!connected && Keyboard.current.spaceKey.wasPressedThisFrame)
            _ = ConnectAsync();
        if (Keyboard.current.escapeKey.wasPressedThisFrame && ws != null)
            _ = ws.Close();

        if (connected)
        {
            if (Keyboard.current.pKey.wasPressedThisFrame)
            {
                UI_Pause();
            }
            if (Keyboard.current.rKey.wasPressedThisFrame)
            {
                UI_Reset();
            }
            if (Keyboard.current.sKey.wasPressedThisFrame)
            {
                UI_Status();
            }
            if (Keyboard.current.fKey.wasPressedThisFrame)
            {
                SendFlightState(planeAngleSlider.value, speedSlider != null ? speedSlider.value : currentPlaneSpeed);
            }
            if (Keyboard.current.hKey.wasPressedThisFrame)
            {
                ToggleHelp();
            }
            if (Keyboard.current.mKey.wasPressedThisFrame)
            {
                ToggleHeatmapMode();
            }
            if (Keyboard.current.cKey.wasPressedThisFrame && chartPanel != null)
            {
                chartPanel.gameObject.SetActive(!chartPanel.gameObject.activeSelf);
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

        string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
        string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

        UpdateSliderLabel(angleSliderLabel, $"<color={desiredHex}>Desired Angle: {planeAngleSlider.value:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}°</color>");

        suppressSliderCallback = false;

        float speed = speedSlider != null ? speedSlider.value : currentPlaneSpeed;
        SendFlightState(angle, speed);
    }

    void OnSpeedSliderChanged(float speed)
    {
        if (suppressSliderCallback) return;

        string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
        string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

        UpdateSliderLabel(speedSliderLabel, $"<color={desiredHex}>Desired Speed: {speedSlider.value:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>");

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
        public float yield_point_pa;
        public float max_angle_deg;
        public float max_speed_kmh;
        public float max_stepper_steps;
        public float new_angle_of_attack;
        public float target_angle_of_attack;
        public float new_speed;
        public float target_speed;
        public int stepper_position;
        public List<CycleBin> cycles_binned;
    }

    [Serializable]
    public class CycleBin
    {
        public float range;
        public float count;
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
