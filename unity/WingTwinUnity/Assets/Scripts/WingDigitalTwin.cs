using NativeWebSocket;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UIElements;

public partial class WingDigitalTwin : MonoBehaviour
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

    private Mesh mesh;
    private Vector3[] originalVertices;
    private Vector3[] deformedVertices;
    private float stressMin;
    private float stressMax;
    private float yieldPointPa = 100_000_000f;

    private Color[] vertexColors;
    private float[] meshStressValues;

    private Dictionary<string, Action<string>> pendingCommands = new Dictionary<string, Action<string>>();
    private readonly Queue<Action> mainThreadQueue = new Queue<Action>();

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

    private Camera GetActiveCamera()
    {
        foreach (Camera cam in Camera.allCameras)
            if (cam.isActiveAndEnabled) return cam;
        return null;
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

    public void SendFlightState(float angle, float speed)
    {
        SendCommand("set_flight_state", new Dictionary<string, object> { { "angle", angle }, { "speed", speed } });
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
