using NativeWebSocket;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UIElements;

public class WingDigitalTwin : MonoBehaviour
{
    [Header("UI Document")]
    [SerializeField] private UIDocument uiDocument;

    [Header("Connection")]
    [SerializeField] private string serverUrl = "ws://localhost:8765";
    [SerializeField] private float reconnectDelay = 2f;
    [SerializeField] private float maxReconnectDelay = 10f;
    [SerializeField] private float heartbeatInterval = 10f;

    [Header("Notifications")]
    [SerializeField] private ToastManager toastManager;
    public int stressBarHeight = 150;
    public int stressBarWidth = 14;

    [Header("Wing Visualization")]
    [SerializeField] private Renderer wingRenderer;
    [SerializeField] private Gradient stressGradient;
    [SerializeField] private bool usePerVertexHeatmap = true;

    [Header("PlaneVisualization")]
    [SerializeField] GameObject rotationalPivot;
    [SerializeField] GameObject planeScene;
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
    private float[] stressField = Array.Empty<float>();
    private float[] deformationField = Array.Empty<float>();
    private float[] nodeDamages = Array.Empty<float>();
    private bool showDamageHeatmap = false;

    // UI Toolkit element references
    private VisualElement damageSliderFill;
    private Label damageLabel;
    private VisualElement avgDamageSliderFill;
    private Label avgDamageLabel;
    private Label speedLabel;
    private Label confidenceLabel;
    private Label connectionLabel;
    private Toggle heatmapToggle;
    private VisualElement stressBar;

    private Slider planeAngleSlider;
    private Slider stepsSlider;
    private Slider speedSlider;
    private VisualElement allowedAngleFill;
    private VisualElement allowedSpeedFill;
    private Label angleSliderLabel;
    private Label stepsSliderLabel;
    private Label speedSliderLabel;


    private VisualElement helpPanel;
    private VisualElement[] viewGroups;

    private Label[] stressLabels;
    private Label planeSpeedLabel;
    private Label planeAngleLabel;

    private VisualElement leftPanel;
    private VisualElement stressLegend;
    private VisualElement notificationContainer;

    private GameObject view3Axes;
    private GameObject axisXObj;
    private GameObject axisYObj;

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
    private readonly System.Collections.Generic.Queue<Action> mainThreadQueue =
        new System.Collections.Generic.Queue<Action>();

    async void Start()
    {
        if (!QueryUIElements())
        {
            Debug.LogError("UI Toolkit initialization failed. UI will not be available.");
            return;
        }
        CreateStressBar();
        CreateAxes();

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

        if (heatmapToggle != null)
        {
            heatmapToggle.RegisterValueChangedCallback(evt => OnHeatmapModeChanged(evt.newValue));
            heatmapToggle.SetValueWithoutNotify(false);
        }
        UpdateHeatmapToggleLabel(false);

        planeAngleSlider.RegisterValueChangedCallback(evt => OnAngleSliderChanged(evt.newValue));
        if (speedSlider != null)
            speedSlider.RegisterValueChangedCallback(evt => OnSpeedSliderChanged(evt.newValue));

        planeAngleSlider.lowValue = -maxAngleDeg;
        planeAngleSlider.highValue = maxAngleDeg;

        if (stepsSlider != null)
        {
            stepsSlider.lowValue = 0f;
            stepsSlider.highValue = maxStepperSteps;
        }
        if (speedSlider != null)
        {
            speedSlider.lowValue = 0f;
            speedSlider.highValue = maxSpeedKmh;
        }

        await ConnectAsync();
    }

    private bool QueryUIElements()
    {
        if (uiDocument == null)
            uiDocument = GetComponent<UIDocument>();
        if (uiDocument == null || uiDocument.rootVisualElement == null)
        {
            Debug.LogError("UIDocument not found or not initialized. Add UIDocument component to this GameObject.");
            return false;
        }

        var root = uiDocument.rootVisualElement;

        damageSliderFill = root.Q("damage-slider-fill");
        damageLabel = root.Q<Label>("damage-label");
        avgDamageSliderFill = root.Q("avg-damage-slider-fill");
        avgDamageLabel = root.Q<Label>("avg-damage-label");
        speedLabel = root.Q<Label>("speed-label");
        confidenceLabel = root.Q<Label>("confidence-label");
        connectionLabel = root.Q<Label>("connection-label");
        heatmapToggle = root.Q<Toggle>("heatmap-toggle");
        if (heatmapToggle != null)
        {
            var checkmark = heatmapToggle.Q(null, "unity-toggle__checkmark");
            if (checkmark != null)
            {
                checkmark.style.borderTopWidth = 1;
                checkmark.style.borderBottomWidth = 1;
                checkmark.style.borderLeftWidth = 1;
                checkmark.style.borderRightWidth = 1;
                var bColor = new Color(0, 0, 0, 0.35f);
                checkmark.style.borderTopColor = bColor;
                checkmark.style.borderRightColor = bColor;
                checkmark.style.borderBottomColor = bColor;
                checkmark.style.borderLeftColor = bColor;
                checkmark.style.borderTopLeftRadius = 3;
                checkmark.style.borderTopRightRadius = 3;
                checkmark.style.borderBottomLeftRadius = 3;
                checkmark.style.borderBottomRightRadius = 3;
            }
        }
        stressBar = root.Q("stress-bar");

        planeAngleSlider = root.Q<Slider>("angle-slider");
        stepsSlider = root.Q<Slider>("steps-slider");
        speedSlider = root.Q<Slider>("speed-slider");
        allowedAngleFill = root.Q("allowed-angle-fill");
        allowedSpeedFill = root.Q("allowed-speed-fill");
        angleSliderLabel = root.Q<Label>("angle-slider-label");
        stepsSliderLabel = root.Q<Label>("steps-slider-label");
        speedSliderLabel = root.Q<Label>("speed-slider-label");

        helpPanel = root.Q("help-panel");

        Button helpBtn = root.Q<Button>("help-button");
        if (helpBtn != null)
            helpBtn.clicked += () => ToggleHelp();
        Button helpCloseBtn = root.Q<Button>("help-close-btn");
        if (helpCloseBtn != null)
            helpCloseBtn.clicked += () => ToggleHelp();

        Button viewBtn1 = root.Q<Button>("view-btn-1");
        Button viewBtn2 = root.Q<Button>("view-btn-2");
        Button viewBtn3 = root.Q<Button>("view-btn-3");
        if (viewBtn1 != null) viewBtn1.clicked += () => SwitchViewButton(1);
        if (viewBtn2 != null) viewBtn2.clicked += () => SwitchViewButton(2);
        if (viewBtn3 != null) viewBtn3.clicked += () => SwitchViewButton(3);

        viewGroups = new VisualElement[3];
        viewGroups[0] = root.Q("view-group-1");
        viewGroups[1] = root.Q("view-group-2");
        viewGroups[2] = root.Q("view-group-3");

        leftPanel = root.Q("left-panel");
        stressLegend = root.Q("stress-legend");
        notificationContainer = root.Q("notification-container");

        stressLabels = new Label[6];
        for (int i = 0; i < 6; i++)
            stressLabels[i] = root.Q<Label>($"stress-label-{i}");

        planeSpeedLabel = root.Q<Label>("plane-speed-label");
        planeAngleLabel = root.Q<Label>("plane-angle-label");

        Color allowedFillColor = new Color(0f, 0.86f, 0.31f, 0.55f);
        if (allowedAngleFill != null)
            allowedAngleFill.style.backgroundColor = allowedFillColor;
        if (allowedSpeedFill != null)
            allowedSpeedFill.style.backgroundColor = allowedFillColor;

        UpdateLegendValues();
        return true;
    }

    private void UpdatePlaneSpeed()
    {
        if (planeSpeedLabel != null)
            planeSpeedLabel.text = $"Current Plane Speed: {currentPlaneSpeed:F1}";

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
        if (rotationalPivot != null)
            rotationalPivot.transform.localRotation = Quaternion.Euler(currentPlaneAngle, 0, 0);

        if (planeAngleLabel != null)
            planeAngleLabel.text = $"Current Plane Angle: {currentPlaneAngle:F1}";
    }

    private Camera GetActiveCamera()
    {
        foreach (Camera cam in Camera.allCameras)
            if (cam.isActiveAndEnabled) return cam;
        return null;
    }

    private void UpdatePlaneLabelPositions()
    {
        Camera cam = GetActiveCamera();
        if (cam == null || rotationalPivot == null)
            return;

        Vector3 screenPos = cam.WorldToScreenPoint(rotationalPivot.transform.position);

        if (screenPos.z < 0f)
        {
            if (planeSpeedLabel != null) planeSpeedLabel.style.display = DisplayStyle.None;
            if (planeAngleLabel != null) planeAngleLabel.style.display = DisplayStyle.None;
            return;
        }

        float x = screenPos.x;
        float y = Screen.height - screenPos.y;

        if (planeSpeedLabel != null)
        {
            planeSpeedLabel.style.display = DisplayStyle.Flex;
            planeSpeedLabel.style.left = x - 80;
            planeSpeedLabel.style.top = y - 50;
        }
        if (planeAngleLabel != null)
        {
            planeAngleLabel.style.display = DisplayStyle.Flex;
            planeAngleLabel.style.left = x - 80;
            planeAngleLabel.style.top = y - 28;
        }
    }

    public void SwitchViewButton(int camera)
    {
        SwitchView(camera);
    }

    private void SwitchView(int camera)
    {
        int index = camera - 1;
        bool planeSceneNeeded = false;

        for (int i = 0; i < UIViewGroups.Count; i++)
        {
            GameObject viewCamera = UIViewGroups[i].viewCamera;
            GameObject worldUIGroup = UIViewGroups[i].worldUIViewGroup;

            bool active = i == index;

            if (worldUIGroup != null)
                worldUIGroup.SetActive(active);
            if (viewCamera != null)
                viewCamera.SetActive(active);
            if (active && UIViewGroups[i].needPlaneScene)
                planeSceneNeeded = true;
        }

        for (int i = 0; i < viewGroups.Length; i++)
        {
            if (viewGroups[i] != null)
                viewGroups[i].style.display = i == index ? DisplayStyle.Flex : DisplayStyle.None;
        }

        bool isView1 = index == 0;
        if (leftPanel != null)
            leftPanel.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;
        if (stressLegend != null)
            stressLegend.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;
        if (notificationContainer != null)
            notificationContainer.style.display = isView1 ? DisplayStyle.Flex : DisplayStyle.None;

        planeScene.SetActive(planeSceneNeeded);

        if (view3Axes != null)
            view3Axes.SetActive(index == 2);
    }

    void CreateStressBar()
    {
        Texture2D tex = MakeGradientTexture(stressGradient);
        if (stressBar != null)
        {
            stressBar.style.backgroundImage = new StyleBackground(Background.FromTexture2D(tex));
        }
    }

    void CreateAxes()
    {
        view3Axes = new GameObject("View3Axes");
        Transform parent = planeScene != null ? planeScene.transform : null;
        if (parent != null)
            view3Axes.transform.SetParent(parent);
        view3Axes.transform.localPosition = Vector3.zero;
        view3Axes.transform.localRotation = Quaternion.identity;
        view3Axes.transform.localScale = Vector3.one;
        view3Axes.SetActive(false);

        float length = 100f;
        float thickness = 0.3f;

        axisXObj = CreateAxisBar(view3Axes.transform, "AxisX", Vector3.right, length, thickness, Color.red);
        axisYObj = CreateAxisBar(view3Axes.transform, "AxisY", Vector3.up, length, thickness, Color.red);
    }

    GameObject CreateAxisBar(Transform parent, string name, Vector3 dir, float length, float thickness, Color color)
    {
        GameObject go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = name;
        go.transform.SetParent(parent);
        go.transform.localPosition = Vector3.zero;
        go.transform.localRotation = Quaternion.FromToRotation(Vector3.up, dir);
        go.transform.localScale = new Vector3(thickness, length * 2, thickness);

        UnityEngine.Object.Destroy(go.GetComponent<BoxCollider>());

        Shader shader = Shader.Find("Unlit/Color");
        if (shader == null) shader = Shader.Find("Sprites/Default");
        if (shader != null)
        {
            Material mat = new Material(shader);
            mat.color = color;
            go.GetComponent<MeshRenderer>().material = mat;
        }
        return go;
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

    void UpdateLegendValues()
    {
        if (stressLabels == null)
            return;

        int labelCount = stressLabels.Length;

        if (showDamageHeatmap)
        {
            for (int i = 0; i < labelCount; i++)
            {
                float t = 1f - (float)i / (labelCount - 1);
                float value = Mathf.Lerp(0f, 1f, t);
                string suffix = i == 0 ? " Max" : i == labelCount - 1 ? " Min" : "";
                if (stressLabels[i] != null)
                    stressLabels[i].text = $"{value:P0}{suffix}";
            }
        }
        else
        {
            for (int i = 0; i < labelCount; i++)
            {
                float t = 1f - (float)i / (labelCount - 1);
                float value = Mathf.Lerp(0f, yieldPointPa, t);
                string suffix = i == 0 ? " Max" : i == labelCount - 1 ? " Min" : "";
                if (stressLabels[i] != null)
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
            ws.SendText("{\"cmd\":\"ping\"}");
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
            stressMin = data.stress_min;
            stressMax = data.stress_max;
            yieldPointPa = data.yield_point_pa > 0 ? data.yield_point_pa : yieldPointPa;
            if (data.max_angle_deg > 0) {
                maxAngleDeg = data.max_angle_deg;
                planeAngleSlider.lowValue = -maxAngleDeg;
                planeAngleSlider.highValue = maxAngleDeg;

            }
            if (data.max_speed_kmh > 0) {
                maxSpeedKmh = data.max_speed_kmh;
                speedSlider.highValue = maxSpeedKmh;
            }
            if (data.max_stepper_steps > 0) {
                maxStepperSteps = data.max_stepper_steps;
                stepsSlider.highValue = maxStepperSteps;
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
                angleSliderLabel.text = $"<color={desiredHex}>Desired Angle: {planeAngleSlider.value:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}{'\u00b0'}</color>";
            if (speedSliderLabel != null)
                speedSliderLabel.text = $"<color={desiredHex}>Desired Speed: {speedSlider.value:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>";

            if (stepsSlider != null)
                stepsSlider.SetValueWithoutNotify(data.stepper_position);
            if (allowedAngleFill != null && maxAngleDeg > 0f)
            {
                float pct = (targetAngleOfAttack + maxAngleDeg) / (2f * maxAngleDeg) * 100f;
                allowedAngleFill.style.width = Length.Percent(Mathf.Clamp(pct, 0f, 100f));
            }
            if (allowedSpeedFill != null && maxSpeedKmh > 0f)
            {
                float pct = targetPlaneSpeed / maxSpeedKmh * 100f;
                allowedSpeedFill.style.width = Length.Percent(Mathf.Clamp(pct, 0f, 100f));
            }

            if (data.stress_field != null && data.stress_field.Count > 0)
                stressField = data.stress_field.ToArray();
            if (data.deformation_field != null && data.deformation_field.Count > 0)
                deformationField = data.deformation_field.ToArray();
            if (data.node_damages != null && data.node_damages.Count > 0)
                nodeDamages = data.node_damages.ToArray();

            Enqueue(UpdateUI);
            Enqueue(() => ProcessNotifications(data.notifications));
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
        UpdateDamageSlider(damageSliderFill, damageLabel, currentDamage, "Max Damage");
        UpdateDamageSlider(avgDamageSliderFill, avgDamageLabel, currentAvgDamage, "Avg Damage");

        if (speedLabel != null) speedLabel.text = $"Vmax: {currentSpeed}%";
        if (confidenceLabel != null) confidenceLabel.text = $"Confidence: {currentConfidence:F1}%";
    }

    void ProcessNotifications(List<NotificationData> notifications)
    {
        if (notifications == null || toastManager == null)
            return;

        foreach (var notif in notifications)
        {
            if (string.IsNullOrEmpty(notif.id))
                continue;

            toastManager.Show(notif.id, notif.type, notif.title, notif.message, OnNotificationDismissed);
        }
    }

    void OnNotificationDismissed(string notificationId)
    {
        SendCommand("dismiss_notification", new Dictionary<string, object>
        {
            { "notification_id", notificationId }
        });
    }

    void UpdateDamageSlider(VisualElement fill, Label label, float value, string title)
    {
        if (fill != null)
        {
            fill.style.width = Length.Percent(value * 100f);
            Color sliderColor = value switch
            {
                >= 0.8f => redColor,
                >= 0.3f => yellowColor,
                _ => greenColor,
            };
            fill.style.backgroundColor = sliderColor;
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
                UpdateDamageHeatmap();
            else if (stressField.Length > 0)
                UpdateHeatmap();
        }
        else
        {
            float t = Mathf.Clamp01(currentDamage);
            Color stressColor = stressGradient.Evaluate(t);
            wingRenderer.material.color = stressColor;
        }

        if (deformationField.Length > 0)
            UpdateDeformation();

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
                UI_Pause();
            if (Keyboard.current.rKey.wasPressedThisFrame)
                UI_Reset();
            if (Keyboard.current.sKey.wasPressedThisFrame)
                UI_Status();
            if (Keyboard.current.fKey.wasPressedThisFrame)
                SendFlightState(planeAngleSlider.value, speedSlider != null ? speedSlider.value : currentPlaneSpeed);
            if (Keyboard.current.hKey.wasPressedThisFrame)
                ToggleHelp();
            if (Keyboard.current.mKey.wasPressedThisFrame)
                ToggleHeatmapMode();
            if (Keyboard.current.cKey.wasPressedThisFrame && chartPanel != null)
                chartPanel.gameObject.SetActive(!chartPanel.gameObject.activeSelf);
        }

        if (connectionLabel != null)
        {
            connectionLabel.text = connected ? "CONNECTED" : "DISCONNECTED";
            connectionLabel.style.color = connected ? Color.green : Color.red;
        }

        UpdatePlaneAngle();
        UpdatePlaneSpeed();
        UpdatePlaneLabelPositions();
    }

    public void ToggleHelp()
    {
        if (helpPanel != null)
            helpPanel.style.display = helpPanel.style.display == DisplayStyle.None ? DisplayStyle.Flex : DisplayStyle.None;
    }

    public void ToggleHeatmapMode()
    {
        showDamageHeatmap = !showDamageHeatmap;
        if (heatmapToggle != null)
            heatmapToggle.SetValueWithoutNotify(showDamageHeatmap);
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
        if (heatmapToggle != null)
            heatmapToggle.label = isDamageMode ? "Damage" : "Stress";
    }

    public void UI_Pause()  => SendCommand("pause");
    public void UI_Reset()  => SendCommand("reset",
        new Dictionary<string, object> { { "target", "damage" } });
    public void UI_Status() => SendCommand("status");

    void OnAngleSliderChanged(float angle)
    {
        string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
        string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

        UpdateSliderLabel(angleSliderLabel, $"<color={desiredHex}>Desired Angle: {planeAngleSlider.value:F1}</color> | <color={allowedHex}>Allowed Angle: {targetAngleOfAttack:F1}{'\u00b0'}</color>");

        float speed = speedSlider != null ? speedSlider.value : currentPlaneSpeed;
        SendFlightState(angle, speed);
    }

    void OnSpeedSliderChanged(float speed)
    {
        string desiredHex = "#" + ColorUtility.ToHtmlStringRGB(desiredColor);
        string allowedHex = "#" + ColorUtility.ToHtmlStringRGB(allowedColor);

        UpdateSliderLabel(speedSliderLabel, $"<color={desiredHex}>Desired Speed: {speedSlider.value:F1}</color> | <color={allowedHex}>Allowed Speed: {targetPlaneSpeed:F1} km/h</color>");

        float angle = planeAngleSlider != null ? planeAngleSlider.value : 0f;
        SendFlightState(angle, speed);
    }

    void UpdateSliderLabel(Label label, string text)
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
        public List<NotificationData> notifications;
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
    public class NotificationData
    {
        public string id;
        public string type;
        public string title;
        public string message;
        public double timestamp;
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
