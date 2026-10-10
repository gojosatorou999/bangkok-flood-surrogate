"""Zero-shot CLIP prompts per class. See docs/VARUN_IMPLEMENTATION.md §6 T50."""

PROMPTS = {
    "NORMAL": [
        "a CCTV photo of a dry city road with visible lane markings",
        "a traffic camera image of a wet road after rain, no standing water",
    ],
    "WATERLOGGING": [
        "a CCTV photo of a road with puddles and standing water patches",
        "a traffic camera image where lane markings are partly covered by water",
    ],
    "FLOODING": [
        "a CCTV photo of a flooded street with water across all lanes",
        "a traffic camera image of cars driving through flood water making waves",
    ],
    "SEVERE_FLOODING": [
        "a CCTV photo of deep flood water above car wheels",
        "a traffic camera image of a road closed by deep flooding",
    ],
    "UNUSABLE": [
        "a black or blank camera image",
        "a blurry camera image covered with raindrops",
    ],
}
