SELECT 
    u.id,
    u.username,
    COUNT(f.flash_friend_id) AS total_flash_friends
FROM 
    skins_bonkuser u
JOIN 
    skins_flashfriendship f ON u.id = f.user_id
GROUP BY 
    u.id, u.username
ORDER BY 
    total_flash_friends DESC
LIMIT 10;



SELECT 
    u.id,
    u.username,
    COUNT(*) AS total_friends,
    RANK() OVER (ORDER BY COUNT(*) DESC) AS rank
FROM 
    skins_bonkuser u
JOIN (
    SELECT player_high_id AS player_id FROM skins_friendship
    UNION ALL
    SELECT player_low_id AS player_id FROM skins_friendship
) f ON u.id = f.player_id
GROUP BY 
    u.id, u.username
ORDER BY 
    total_friends DESC
LIMIT 200;
